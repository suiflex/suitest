/** Warns that a sign-in spends a session the vendor has not licensed for this.
 *
 * Some of the sign-ins Suitest offers reach an endpoint meant for that vendor's
 * own client — the ChatGPT plan behind Codex, Code Assist behind the Gemini CLI.
 * They work, and they are why the feature is worth having, but the account
 * carrying them can be rate-limited or closed for it.
 *
 * That was documented in code comments and in docs/, which is exactly where the
 * person about to click the button will not look. It belongs next to the button.
 */
export function UnlicensedSessionNotice({
  what,
}: {
  /** What the session is spent on, e.g. "your ChatGPT plan". */
  what: string;
}): React.ReactElement {
  return (
    <p
      role="note"
      data-testid="unlicensed-session-notice"
      className="rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12.5px] text-amber"
    >
      <strong className="font-medium">Risk notice.</strong> This uses {what} through an endpoint the
      vendor has not licensed for third-party clients. It may stop working without warning, and the
      account could be rate-limited or closed. Use an API key instead if that matters to you.
    </p>
  );
}
