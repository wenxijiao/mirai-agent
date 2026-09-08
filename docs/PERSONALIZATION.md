# Personalization categories

The app labels its two areas **Yumi’s behavior** and **About you**.

- **Yumi’s behavior**: response language, tone, length, formatting, and assistant workflow rules. Existing `preference`, `communication_style`, `constraint`, and `do_not_assume` kinds remain compatible. Here `preference` means a preference about the assistant’s behavior, not every everyday use of that word.
- **About you**: personal tastes, dietary restrictions, background, interests, habits, relationships, and projects. Food likes/dislikes use `profile`, even when expressed as “avoid these ingredients in recommendations.” Other supported personal memory kinds remain available.

Classify by meaning, not by whether a sentence says “remember,” “prefer,” or “please.” Do not duplicate the same information in both sections or turn a personal fact into an invented workflow rule. Both the tool schema and runtime personalization prompt explain this distinction. Reply-language requests keep their dedicated setting.

The app creates and edits items within the tab the user opened; its editor does not switch categories. The API retains category-only updates for compatibility: a category-only `PUT /assistant/memories/{id}` preserves the id, content, creation timestamp and source-event links, and creates no forgetting tombstone. Existing entries are not guessed or automatically reclassified by a migration. This keeps a user’s manual organization authoritative.

Behavior rules are included in the explicit personalization block. Personal memories remain available through stable context and relevance retrieval; they inform appropriate answers without overriding response language, current requests, tool permissions, or platform rules.
