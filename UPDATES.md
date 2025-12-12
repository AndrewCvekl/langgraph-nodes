# Recent Updates

## 2025-01-12 - Fixed Message Display Before Interrupts

### Bug Fix: Messages Now Display Before Interrupt Prompts

**Problem:** When a node added messages to `assistant_messages` and then immediately proceeded to a node with an interrupt, the messages weren't displayed until after all interrupts were resolved. This made the conversation flow confusing.

**Example of the bug:**
```
User: "Song with lyrics purple haze"
[Interrupt immediately shows]: Do you want to have a listen?
```

The song identification message ("I think you're thinking of 'Purple Haze' by Jimi Hendrix...") was being skipped!

**First Attempt:** Modified `app/main.py` to print `assistant_messages` BEFORE showing each interrupt prompt.

**That didn't work!** The messages still weren't appearing. 

**Attempted Fix #1:** Changed `lyrics_catalogue_lookup` to use `Command` instead of returning a plain dict - **Still didn't work!**

**Root Cause (Discovered):** When you wrap a subgraph in a function and invoke it (e.g., `lyrics_subgraph.invoke(state, config)`), the function doesn't return until all interrupts within the subgraph are resolved. So state updates from nodes inside the subgraph aren't merged back to the parent until the entire subgraph completes.

**Real Solution:** Add the compiled subgraph **directly** as a node (not wrapped in a function):
```python
# Before (didn't work):
builder.add_node("run_lyrics_subgraph", run_lyrics_subgraph)  # wrapper function

# After (works!):
builder.add_node("run_lyrics_subgraph", lyrics_subgraph)  # compiled subgraph directly
```

When added directly, LangGraph treats each node within the subgraph as part of the parent graph's execution flow, committing state updates at each step.

**Now works correctly:**
```
User: "Song with lyrics purple haze"
Bot: I think you're thinking of "Purple Haze" by Jimi Hendrix.
     Unfortunately, it's not currently in our catalogue.
[Interrupt]: Do you want to have a listen?
```

### Files Modified
- `app/main.py` - Print assistant messages before handling each interrupt + added debug logging
- `app/graphs/lyrics_subgraph.py` - Changed `lyrics_catalogue_lookup` to use `Command` + embedded payment subgraph
- `app/graphs/app_graph.py` - Changed to add `lyrics_subgraph` directly as a node (not wrapped)

### Additional Improvements
- Embedded `payment_subgraph` within `lyrics_subgraph` for cleaner flow
- Added `TECHNICAL_NOTES.md` documenting subgraph integration patterns

---

## 2025-01-12 - Improved Lyrics Search Flow

### Changes to Lyrics Search Conversation Flow

The lyrics search flow has been improved to be more natural and conversational.

#### Old Flow (Before)
1. User provides lyrics
2. Bot: "I think it's [Song] by [Artist]. It is/isn't in our catalogue. Want to listen?"
3. User: Yes
4. [YouTube player shows]
5. Bot: "Want to buy?" OR "Want to request?"

**Problem:** The identification and listen question were combined, making it feel rushed.

#### New Flow (After)
1. User provides lyrics
2. **Bot: "I think you're thinking of [Song] by [Artist]. Great news - it's in our catalogue for $X.XX."** *(or "Unfortunately, it's not currently in our catalogue.")*
3. **Bot: "Do you want to have a listen?"**
4. User: Yes
5. [YouTube player shows]
6. **If in catalogue:** Bot: "Do you want to purchase it for $X.XX?"
7. **If NOT in catalogue:** Bot: "Is this the sort of song you'd be interested in seeing in our catalogue?"

### Why This Is Better

✅ **Clearer identification step** - User gets confirmation about what song was found before committing to listen

✅ **Catalogue status is clear upfront** - No surprises about whether it's available to buy

✅ **More natural pacing** - Information flows in logical steps rather than all at once

✅ **Relevant questions only** - Purchase question only for catalogue songs, interest question only for non-catalogue songs

### Example Conversation

**User:** "What song has the lyrics 'Is this the real life'"

**Bot:** "I think you're thinking of 'Bohemian Rhapsody' by Queen. Great news - it's in our catalogue for $0.99."

**[Interrupt - Do you want to have a listen?]**

**User:** Yes

**Bot:** *[Shows YouTube player with autoplay]*

**Bot:** "Do you want to purchase it for $0.99?"

**[Interrupt - Purchase confirmation]**

---

**Alternative - Song NOT in catalogue:**

**User:** "Song that goes 'never gonna give you up'"

**Bot:** "I think you're thinking of 'Never Gonna Give You Up' by Rick Astley. Unfortunately, it's not currently in our catalogue."

**[Interrupt - Do you want to have a listen?]**

**User:** Yes

**Bot:** *[Shows YouTube player with autoplay]*

**Bot:** "Is this the sort of song you'd be interested in seeing in our catalogue?"

**[Interrupt - Interest confirmation]**

**User:** Yes

**Bot:** "Great! I've noted your interest. We'll consider adding this song to our catalogue. Is there anything else I can help with?"

### Files Modified

- `app/graphs/lyrics_subgraph.py`
  - `lyrics_catalogue_lookup()` - Separated identification from listen question
  - `lyrics_interrupt_listen_confirm()` - Updated question text
  - `lyrics_render_player_and_offer()` - Updated purchase/request question wording
  - `lyrics_interrupt_request_confirm()` - Improved response messages

### Technical Notes

The node flow remains the same (10 nodes total):
- B0: Extract lyrics query
- B1: Search Genius
- B2: Check catalogue (NOW: just informational)
- B3: Ask to listen (interrupt)
- B4: Fetch YouTube
- B5: Show player + ask purchase/request
- B6: Purchase interrupt (if in catalogue)
- B7: Payment flow (if purchasing)
- B8: Request interrupt (if not in catalogue)
- B9: Done

No new nodes added - just improved messaging within existing nodes to make the conversation flow more naturally.

