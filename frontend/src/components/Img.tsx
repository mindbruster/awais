/**
 * A picture that never shows a broken frame.
 *
 * Every image in this system points at a file on the shop's own disk or in its
 * object storage, and a URL on a record is not a promise the file is still
 * there. Files get moved when storage changes, deleted when somebody prunes a
 * folder, and renamed by a migration nobody remembered touched images. When
 * that happens a bare `<img>` shows the browser's broken-image glyph — the
 * torn page — which reads to a shopkeeper as *the software is broken*, not as
 * *this photograph is missing*.
 *
 * Two failures, and they are different states worth distinguishing:
 *
 *   no `src` at all      the piece was never photographed. Ordinary.
 *   `src` that 404s      the file was expected and is gone. Worth noticing.
 *
 * Both render the fallback rather than a torn page, but the second is the one
 * somebody should eventually look into, so it carries a title a hover reveals.
 *
 * `onError` fires once and flips to the fallback. It is deliberately not retried
 * — a missing file does not become present because the page asked twice, and a
 * retry loop on a gallery of two hundred pieces is a self-inflicted flood.
 */
import { useEffect, useState } from "react";
import { staticUrl } from "@/lib/url";

export function Img({
  src,
  alt,
  className = "",
  fallbackClassName = "",
  /** Shown in place of the picture. Initials, a serial, an icon — or nothing. */
  fallback = null,
  loading = "lazy",
}: {
  src: string | null | undefined;
  alt: string;
  className?: string;
  fallbackClassName?: string;
  fallback?: React.ReactNode;
  loading?: "lazy" | "eager";
}) {
  const [failed, setFailed] = useState(false);

  // A new src deserves a fresh attempt. Without this, one broken picture in a
  // list would keep its failed state as the component is reused for the next
  // row, and a whole gallery could go blank after a single missing file.
  useEffect(() => setFailed(false), [src]);

  const url = staticUrl(src);

  if (!url || failed) {
    return (
      <div
        className={fallbackClassName || className}
        aria-hidden={!alt}
        title={failed ? `Image could not be loaded: ${src}` : undefined}
      >
        {fallback}
      </div>
    );
  }

  return (
    <img
      src={url}
      alt={alt}
      loading={loading}
      className={className}
      onError={() => setFailed(true)}
    />
  );
}
