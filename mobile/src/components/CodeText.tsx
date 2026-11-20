import React, {memo, useMemo} from 'react';
import {Text, type TextStyle} from 'react-native';
import {useTheme} from '../theme/theme';
import {CODE_THEMES, highlightCode} from '../utils/highlight';

/** Source text in the web console's GitHub colours; unknown languages are guessed when short. */
function CodeTextImpl({code, lang, style}: {code: string; lang?: string; style?: TextStyle}) {
  const t = useTheme();
  const tokens = useMemo(() => highlightCode(code, lang), [code, lang]);
  const palette = t.isDark ? CODE_THEMES.dark : CODE_THEMES.light;
  return (
    <Text selectable style={[style, {color: palette.base}]}>
      {tokens.map((tok, i) => {
        const color = tok.scope ? palette.scopes[tok.scope] : undefined;
        return color ? (
          <Text key={i} style={{color}}>
            {tok.text}
          </Text>
        ) : (
          tok.text
        );
      })}
    </Text>
  );
}

export const CodeText = memo(CodeTextImpl);
