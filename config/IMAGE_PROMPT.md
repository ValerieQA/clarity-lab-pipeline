# Clarity Lab — Image Generation Prompt

## Master Image Rules

Create a still photograph for a reflective article titled "{title}".

Register: quiet documentary still life. Real light, real surfaces, nothing staged for the camera. The photograph looks found rather than produced — as if someone noticed something and photographed it before the light changed.

Not advertising. Not a lifestyle shoot. Not an interiors catalogue.

Subject family: {subject_state}.
Composition: {composition_state}.
Light: {light_state}.
Palette: {visual_state_palette}.
Mood: {visual_state_mood}.
Optional accent: {accent_state}.
Journey state name, for reference only: {visual_state_name}.

**Do not illustrate the article.** The image sets a register; it does not explain the text. No visual metaphor for the idea, no symbol standing in for the argument. If the subject family says stone, photograph stone — not stone that means something.

Context for tone only, not for subject matter: {core_observation}

No people. No faces. No silhouettes. No body parts. No hands. No reflections of a person.
No text. No letters. No numbers. No logos. No monograms. No signage.

Photographic, not illustrated. Not painterly, not CGI, not a render, not blurry, not HDR.
Square format.

---

## Do not produce

These are the images that appear whenever a model is asked for "quiet" and "reflective". Every one of them is a cliché and none may be generated.

- Zen stones stacked or balanced
- A single lit candle
- A minimal white desk with a laptop and a small plant
- A coffee cup by a window, especially held or steaming
- An open book on a bed or a blanket
- A mirror, a reflection used as a metaphor, or anything mirror-shaped
- A door standing ajar
- A path, a road, a bridge, a staircase used as a journey
- A single feather, a dandelion, a butterfly
- A window with rain drops in soft focus
- Beach, sunset over water, mountains at dawn
- Neatly arranged flat-lay objects on a neutral background
- A chess piece, a compass, a clock, a lightbulb, a keyhole
- Anything arranged in a perfectly centred symmetrical composition

---

## Visual Journey

Palette and mood. Advances one step per published article, wrapping after 13.

0 | Morning Mist | mood: fresh clarity, quiet beginning, soft light | palette: mist blue, pale cream, light stone, soft grey-blue, airy white
1 | Pale Sky | mood: lightness, openness, space to breathe | palette: pale sky blue, cloud white, soft beige, muted horizon blue
2 | Sea Foam | mood: airy calm, subtle movement, emotional spaciousness | palette: sea foam green, blue-grey, soft cream, washed natural tones
3 | Soft Sage | mood: gentle balance, grounded growth, natural quiet | palette: soft sage, muted olive, cream, linen, warm grey
4 | Warm Leaf | mood: natural warmth, subtle energy, living stillness | palette: warm green, muted leaf, beige, soft gold, natural shadow
5 | Sand Dune | mood: comfort, inner stability, warm ground | palette: sand beige, dune cream, pale clay, soft taupe, warm light
6 | Honey Clay | mood: soft warmth, nourishment, quiet presence | palette: honey beige, clay, cream, warm ochre, muted caramel
7 | Linen Earth | mood: earthy depth, quiet introspection, texture | palette: linen, stone, earth beige, warm grey, muted brown
8 | Dust Rose | mood: transition, softening, emotional nuance | palette: dust rose, muted terracotta, soft beige, pale clay, warm shadow
9 | Dusty Blue | mood: deepening, inner depth, calm concentration | palette: dusty blue, slate blue, cream, soft grey, muted navy
10 | Deep Evening | mood: reflection, quiet depth, elegant shadow | palette: deep navy accents, dusty blue, warm cream, muted gold, soft shadow
11 | Twilight | mood: integration, rest, pause before renewal | palette: twilight blue, mauve-grey, muted lilac, soft peach, dusk cream
12 | Return To Mist | mood: renewal, clarity returning, a new cycle | palette: mist blue, pale cream, soft grey-blue, quiet white, distant green

---

## Subject Families

What is physically in the frame. Advances one step per published article, wrapping after 9 — so it drifts against the 13-step palette and the same pairing does not return for years.

0 | interior architecture — a corner where two walls meet, the underside of a stair, a threshold, a section of ceiling, a doorframe seen edge-on. Empty of furniture.
1 | textile and paper — folded linen, a stack of loose paper, a hanging curtain, a creased envelope, canvas, a paper edge catching light
2 | water and glass — a still water surface, an empty glass vessel, condensation on a pane, refraction through thick glass, a shallow puddle on a hard floor
3 | stone and mineral — a plastered wall, a worn floor, a broken fragment, gravel, a marble offcut, raw concrete
4 | one plant, closely — a single stem, the edge of one leaf, dried seedheads, bare branch against a wall. Never a bouquet, never a styled arrangement
5 | furniture at rest — the edge of a chair, a table corner, an empty shelf, the arm of a sofa. Nothing placed on it, nothing arranged
6 | sky and distance — weather, a field of cloud, haze over a horizon, an expanse with almost nothing in it
7 | metal and worn tool — a hinge, a handrail, a door handle, a latch, a scratched surface, patina
8 | shadow as the subject — the cast shape itself falling across a plain surface, the object that makes it out of frame

---

## Composition

How it is framed. Advances one step per published article, wrapping after 7.

0 | extreme close — texture fills the whole frame, scale is ambiguous, no object is fully visible
1 | middle distance — one object placed well off centre, most of the frame empty
2 | wide — the space dominates completely, the subject occupies a small part of the frame
3 | directly overhead, flat, looking straight down
4 | looking through — a near edge or surface partly obscures what is behind it
5 | corner weight — the composition loaded into one corner, a strong diagonal across the frame
6 | divided frame — a horizon or a hard architectural line splitting the image into two unequal fields

---

## Light

What the light is doing. Advances one step per published article, wrapping after 5.

0 | low sun, long raking shadow, hard-edged, strong directional
1 | overcast, shadowless, completely even, flat
2 | one window, bright near it and falling off quickly into deep shadow
3 | late dusk, very low contrast, colour almost drained out
4 | bright light bouncing off an unseen surface, filling the frame indirectly

---

## Accent States

Optional colour accent. Advances one step per published article, wrapping after 6.

0 | muted terracotta
1 | soft golden hour
2 | dusty mauve
3 | muted lilac
4 | deep olive
5 | ocean teal

---

## How the rotation works

Each list advances by one on every published article and wraps independently:

```
palette     = journey[i % 13]
subject     = subjects[i % 9]
composition = compositions[i % 7]
light       = lights[i % 5]
accent      = accents[i % 6]
```

Because 13, 9, 7 and 5 share no common factors, a full combination does not repeat for **4095 articles** — over twenty-five years at three a week. The palette still moves through its familiar thirteen-step arc, so the feed keeps its colour rhythm. What changes is that consecutive images no longer share subject matter, framing and light on top of the colour.

**This is the fix for the sameness.** Previously only the palette rotated. Everything else — "symbolic objects, architecture, natural forms" in "luxury editorial" style — was identical on every single run. Thirteen versions of one photograph, differently tinted.

---

## Editing this file

All five lists are read from this file at run time. Add, remove or rewrite entries by hand; no code change is needed.

One caution: if you change how many entries a list has, the arithmetic changes with it. Keep the counts **13, 9, 7, 5, 6** — or if you must change one, pick a number that shares no factors with the others, otherwise combinations start repeating much sooner.
