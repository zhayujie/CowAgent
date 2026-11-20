import type {StackCardInterpolatedStyle, StackCardInterpolationProps} from '@react-navigation/stack';

/**
 * The iOS slide, with the page underneath drifting a third of the way left.
 * Each card is moved by a single value: Android's new architecture can repaint a
 * transform built from several animated parts with a stale part mid-transition,
 * which shows as the page below jumping or vanishing before the slide ends.
 */
export function forSlide({current, next, layouts}: StackCardInterpolationProps): StackCardInterpolatedStyle {
  const width = layouts.screen.width;
  const translateX = next
    ? next.progress.interpolate({inputRange: [0, 1], outputRange: [0, -width * 0.3], extrapolate: 'clamp'})
    : current.progress.interpolate({inputRange: [0, 1], outputRange: [width, 0], extrapolate: 'clamp'});
  return {cardStyle: {transform: [{translateX}]}};
}
