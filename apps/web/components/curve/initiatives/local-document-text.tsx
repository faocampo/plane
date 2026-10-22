// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import Markdown from "react-markdown";

type Props = { text: string; mediaType?: string; label: string };
/** Large documents retain a faithful plain-text view without synchronous Markdown parsing. */
const FORMATTED_CHARACTER_LIMIT = 256_000;
export function LocalDocumentText({ text, mediaType, label }: Props) {
  if (mediaType !== "text/markdown" || text.length > FORMATTED_CHARACTER_LIMIT) {
    return (
      <pre className="curve-local-prd__text" aria-label={label}>
        {text}
      </pre>
    );
  }
  return (
    <article className="curve-local-prd__markdown" aria-label={label}>
      <Markdown
        components={{
          h1: "h5",
          h2: "h6",
          h3: "h6",
          h4: "h6",
          h5: "h6",
          h6: "h6",
          img: ({ alt }) => (
            <span className="curve-local-prd__image-note">
              Image: {alt || "No description provided"} (external image omitted)
            </span>
          ),
          a: ({ href, children }) =>
            href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
        }}
      >
        {text}
      </Markdown>
    </article>
  );
}
