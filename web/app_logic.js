export function shouldSubmitOnEnter({ key, shiftKey, pending, hasMessage, hasFiles }) {
  return key === "Enter" && !shiftKey && !pending && (hasMessage || hasFiles);
}
