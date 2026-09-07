# Durable voice messages

`POST /assistant/voice` accepts a client-generated UUID (`request_id`), owned
`session_id`, and `content_base64` containing a PCM WAV recording. Audio is saved
before transcription. Retries of the same UUID, session, and bytes reuse the
saved transcript. A different payload or account cannot reuse the UUID.

`POST /chat` accepts optional `voice_id` and `reply_voice`. For voice input, the
server uses the saved transcript as the prompt and atomically binds the original
audio to the saved user message. Concurrent or already-sent recordings return
409, without starting another agent loop. Unbound claims are released on failure;
a five-minute lease permits recovery after a crashed worker. Normal tool
confirmation, personal-context revision, and quota checks remain in force.

Voice replies are marked in the assistant event. `POST /assistant/voice/reply`
accepts the saved `turn_id`, synthesizes only that event's text, and caches all
audio parts. Repeated playback does not regenerate the reply. The owner fetches
`GET /assistant/voice/{id}/audio?part=0` using the ordinary account authorization.
Audio responses use `Cache-Control: private, no-store`; no public media URLs or
provider keys are returned. Deleting the source record makes its audio
inaccessible. Media currently follows the existing soft-deletion policy; files
are not physically purged by deleting a history row.

The SQLite `voice_messages` table is created additively. Media files are stored
beside the database under `voice/<hashed-owner>/` and must be included with normal
persistent-volume backups. Pending uploads that never become messages are retained;
there is no unattended garbage collector in this release.

Tests: `pytest tests/test_voice_messages.py` covers durable bytes/transcripts,
retry deduplication, exclusivity, account isolation, invalid audio, deleted records,
cached replies, prompt integrity, and Unicode speech chunking.
