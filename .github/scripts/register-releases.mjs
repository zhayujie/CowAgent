// Build the D1 upsert SQL for a desktop release from the files in a directory.
//
// Each mac release has TWO artifacts that map to a SINGLE D1 row:
//   - <name>-<arch>.dmg  -> manual download   (filename / size / sha512)
//   - <name>-<arch>.zip  -> auto-update        (update_filename / update_size /
//                                                update_sha512)
// electron-updater's MacUpdater can only consume a zip, never a dmg, so the
// feed serves the zip while the website serves the dmg. Windows has only the
// .exe (stored in the main columns; it's both the download and the update),
// and Android only the .apk, likewise.
//
// We emit ONE `INSERT OR REPLACE` per (version, platform) carrying BOTH halves,
// because two replaces on the same primary key would drop whichever came first.
//
// Usage:
//   node register-releases.mjs --dir dist --version 1.2.0 \
//        --sql out.sql [--latest] 
//
//   --latest  mark these rows is_latest=1 AND clear the previous latest for
//             each platform (used by the publish/promote workflow). Without it
//             rows are written unpublished (is_latest=0) — the build stage.
//
// The iOS app ships through the App Store, so its row carries the store page
// instead of a file; register it once the version is live there:
//   node register-releases.mjs --version 2.3.0 --app-store <App Store URL> \
//        --sql ios.sql --latest
//
// Likewise for an Android app market (ids as the app names them, e.g. xiaomi,
// huawei, play): apps installed from it are told to update there once its row
// says the market carries the version.
//   node register-releases.mjs --version 2.3.0 --market xiaomi --sql m.sql --latest
//
// sha512 is base64 (the exact format electron-updater validates).

import { execSync } from 'node:child_process'
import fs from 'node:fs'

function arg(name, fallback = undefined) {
  const i = process.argv.indexOf(`--${name}`)
  if (i === -1) return fallback
  const next = process.argv[i + 1]
  // Boolean flag (no value or next token is another flag).
  if (next === undefined || next.startsWith('--')) return true
  return next
}

const dir = arg('dir', 'dist')
const version = arg('version')
const sqlPath = arg('sql', 'd1.sql')
const makeLatest = arg('latest', false) === true
const appStore = arg('app-store')
const market = arg('market')

if (!version) {
  console.error('register-releases: --version is required')
  process.exit(1)
}
if (appStore !== undefined && !/^https:\/\//.test(String(appStore))) {
  console.error('register-releases: --app-store needs the https:// URL of the App Store page')
  process.exit(1)
}
// The platform column holds 32 characters, "android-" included.
if (market !== undefined && (typeof market !== 'string' || !/^[a-z0-9]{1,24}$/.test(market))) {
  console.error('register-releases: --market needs a short lowercase id such as xiaomi')
  process.exit(1)
}

const sha512 = (f) =>
  execSync(`openssl dgst -sha512 -binary "${f}" | openssl base64 -A`, {
    shell: '/bin/bash',
  })
    .toString()
    .trim()

// SQL-escape single quotes (base64/keys shouldn't contain them, but be safe).
const q = (s) => String(s).replace(/'/g, "''")

// platform -> { main: {key,size,sha}, upd: {key,size,sha} }
const rows = {}

if (appStore) {
  rows.ios = { main: { key: appStore, size: 0, sha: '' } }
}
if (market) {
  rows[`android-${market}`] = {}
}

for (const base of appStore || market ? [] : fs.readdirSync(dir)) {
  const f = `${dir}/${base}`
  if (fs.statSync(f).isDirectory()) continue

  let platform
  let slot
  if (/arm64\.dmg$/.test(base)) {
    platform = 'mac-arm64'
    slot = 'main'
  } else if (/x64\.dmg$/.test(base)) {
    platform = 'mac-x64'
    slot = 'main'
  } else if (/arm64\.zip$/.test(base)) {
    platform = 'mac-arm64'
    slot = 'upd'
  } else if (/x64\.zip$/.test(base)) {
    platform = 'mac-x64'
    slot = 'upd'
  } else if (/win7.*\.exe$/i.test(base)) {
    // Legacy Win7/8 build (Electron 22). Its artifactName carries a "win7"
    // segment so it never collides with the standard win exe in the same
    // v<version>/ folder — just like arm64/x64 distinguish the two mac builds.
    platform = 'win-legacy'
    slot = 'main'
  } else if (/\.exe$/.test(base)) {
    platform = 'win'
    slot = 'main'
  } else if (/\.apk$/.test(base)) {
    platform = 'android'
    slot = 'main'
  } else {
    console.log('Skipping unrecognized artifact:', base)
    continue
  }

  rows[platform] ||= {}
  rows[platform][slot] = {
    key: `v${version}/${base}`,
    size: fs.statSync(f).size,
    sha: sha512(f),
  }
}

if (Object.keys(rows).length === 0) {
  console.error('register-releases: no recognized artifacts in', dir)
  process.exit(1)
}

const isLatest = makeLatest ? 1 : 0
const sql = []
for (const [platform, r] of Object.entries(rows)) {
  const m = r.main || { key: '', size: 0, sha: '' }
  const u = r.upd || { key: '', size: 0, sha: '' }
  if (makeLatest) {
    // Clear the previous latest for this platform before promoting the new row.
    sql.push(`UPDATE releases SET is_latest = 0 WHERE platform = '${platform}';`)
  }
  sql.push(
    `INSERT OR REPLACE INTO releases ` +
      `(version, platform, filename, size, sha512, update_filename, update_size, update_sha512, is_latest) ` +
      `VALUES ('${version}', '${platform}', '${q(m.key)}', ${m.size}, '${q(m.sha)}', ` +
      `'${q(u.key)}', ${u.size}, '${q(u.sha)}', ${isLatest});`
  )
}

fs.writeFileSync(sqlPath, sql.join('\n') + '\n')
console.log(`register-releases: wrote ${sql.length} statement(s) to ${sqlPath}`)
