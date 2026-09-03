const HTTP_PROTOCOL_PATTERN = /^https?:\/\//i;
const DOMAIN_PATTERN = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;
const IPV4_PATTERN = /^(?:\d{1,3}\.){3}\d{1,3}$/;

const isValidIPv4Address = (hostname: string) =>
  IPV4_PATTERN.test(hostname) && hostname.split(".").every((octet) => Number(octet) <= 255);

export const normalizeQuickLinkUrl = (value: string): string | undefined => {
  const trimmedValue = value.trim();
  if (!trimmedValue) return undefined;

  const normalizedValue = HTTP_PROTOCOL_PATTERN.test(trimmedValue) ? trimmedValue : `http://${trimmedValue}`;

  try {
    const url = new URL(normalizedValue);
    const isSupportedProtocol = url.protocol === "http:" || url.protocol === "https:";
    const isValidHostname =
      url.hostname === "localhost" ||
      DOMAIN_PATTERN.test(url.hostname) ||
      isValidIPv4Address(url.hostname) ||
      (url.hostname.startsWith("[") && url.hostname.endsWith("]"));

    return isSupportedProtocol && isValidHostname ? normalizedValue : undefined;
  } catch {
    return undefined;
  }
};

export const getQuickLinkUrlError = (error: unknown): string | undefined => {
  if (!error || typeof error !== "object" || !("data" in error)) return undefined;

  const data = error.data;
  if (!data || typeof data !== "object" || !("url" in data)) return undefined;

  const urlError = data.url;
  if (typeof urlError === "string") return urlError;
  if (Array.isArray(urlError) && typeof urlError[0] === "string") return urlError[0];
  if (urlError && typeof urlError === "object" && "error" in urlError && typeof urlError.error === "string")
    return urlError.error;

  return undefined;
};
