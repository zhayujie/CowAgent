import {integrationBase} from '../src/utils/integrations';

const lan = ['http://192.168.1.8:9899'];

describe('integrationBase', () => {
  it('prefers the configured public URL', () => {
    expect(integrationBase({public_url: 'https://cow.example.com/', lan_urls: lan}, 'https://tunnel.example.net')).toBe(
      'https://cow.example.com',
    );
  });

  it('keeps the address the app connects with when no public URL is set', () => {
    expect(integrationBase({public_url: '', lan_urls: lan}, 'https://cow.example.com')).toBe('https://cow.example.com');
  });

  it('swaps a loopback connection for a LAN address', () => {
    expect(integrationBase({public_url: '', lan_urls: lan}, 'http://127.0.0.1:9899')).toBe(lan[0]);
    expect(integrationBase({public_url: '', lan_urls: lan}, 'http://localhost:9899')).toBe(lan[0]);
    expect(integrationBase({public_url: '', lan_urls: []}, 'http://127.0.0.1:9899')).toBe('http://127.0.0.1:9899');
  });

  it('falls back to the connection address when the server is not asked', () => {
    expect(integrationBase(null, 'https://cow.example.com/')).toBe('https://cow.example.com');
  });
});
