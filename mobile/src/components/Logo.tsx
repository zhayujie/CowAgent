import React from 'react';
import Svg, {Circle, Path} from 'react-native-svg';

const GREEN = '#5FCE72';

/** The CowAgent mark, drawn as a vector so it stays sharp at any size. */
export function Logo({size}: {size: number}) {
  return (
    <Svg width={size} height={size} viewBox="0 0 100 100">
      <Circle cx={50} cy={50} r={50} fill={GREEN} />
      <Path
        fill="#fff"
        d="M51 79.2H26.2c-1.6 0-2.4-1.3-1.5-2.6l3.5-5.2c.8-1.2.8-2.6.1-3.8A29.5 29.5 0 1 1 51 79.2Z"
      />
      <Circle cx={37.9} cy={43.8} r={3.8} fill={GREEN} />
      <Circle cx={63.2} cy={43.8} r={3.8} fill={GREEN} />
      <Path fill={GREEN} d="M41.6 55.9h18.6c.6 0 1 .5.9 1.1a10.2 10.2 0 0 1-20.4 0c-.1-.6.3-1.1.9-1.1Z" />
    </Svg>
  );
}
