"""The speech-to-text slot. Owner decision 2026-10-21: chosen later (AssemblyAI or Deepgram in the plan); off until
then — no recording is sent anywhere. A transcriber gets the audio (in memory) and returns the conversation as
[{who: customer|business, text, at: seconds into the call}] — it must tell the customer from the agent."""
_transcriber = None


def use(transcriber) -> None:
    global _transcriber
    _transcriber = transcriber


def active():
    return _transcriber
