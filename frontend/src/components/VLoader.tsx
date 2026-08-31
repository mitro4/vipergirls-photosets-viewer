interface VLoaderProps {
  /** px size of the square bounding box. */
  size?: number;
  className?: string;
}

/**
 * Animated "V" loading indicator — a purple light travels along the V stroke.
 * Used as the placeholder while an image is being fetched.
 */
export function VLoader({ size = 40, className }: VLoaderProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      aria-label="Loading"
    >
      {/* V shape: top-left → bottom-center → top-right */}
      <polyline
        points="20,25 50,75 80,25"
        className="vloader-track"
      />
      <polyline
        points="20,25 50,75 80,25"
        className="vloader-light"
      />
    </svg>
  );
}
