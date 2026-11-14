"""Post categories and their tabs (owner decisions 14 Nov 2026; plan in the workspace notes, "contextual tabs").

A post's category picks the tabs its post view shows between Summary and Details: a recipe gets Ingredients and Method,
a music post gets Tracks and Artists, a trip gets Places and Itinerary. This file is only data: the one place to add a
category or a tab. `views.py` turns it into a post's tabs; `hub_views.py` draws each tab by its `render` kind.

Every tab's content is a list of items in one shape (views.ITEM_FIELDS); `ai` tells the AI what an item of that tab is,
`free` names a source that fills the tab without AI (Private mode, or before a post's view is built).
"""

from dataclasses import dataclass

RENDERS = ("checklist", "steps", "cards", "places", "palette", "specs", "proscons", "quotes", "notes", "flashcards",
           "timeline", "event")
FREE_SOURCES = ("", "ingredients", "steps", "list_items", "places", "products", "tools", "chapters", "books_media")
CORE = ("read", "sum", "deep", "links", "rel", "tr", "det")  # the panes hub_card always knew; never used as a tab id here
GROUPS = {"design": "Design & style", "travel_food": "Travel & food", "tech": "Tech & AI", "media": "Music, film & books",
          "life": "Life & how-to", "knowledge": "News & learning", "other": "Other"}


@dataclass(frozen=True)
class Tab:
    id: str
    label: str
    render: str
    ai: str                      # what one item is, and which item fields to fill
    free: str = ""               # a no-AI source (FREE_SOURCES)
    providers: tuple = ()        # search links / lookups for cards (lookups.PROVIDERS ids)
    empty_text: str = "Nothing here for this post."


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    group: str
    blurb: str                   # one line for the AI: what belongs here
    tabs: tuple                  # tab ids in priority order
    lend: str                    # the one tab lent when this is a post's second category
    ask: tuple = ()              # Ask starter questions
    types: tuple = ()            # brain.TYPES that point here (rules guess)
    formats: tuple = ()          # brain.FORMATS that point here
    list_kinds: tuple = ()       # brain.LIST_KINDS that point here
    words: tuple = ()            # words in title, tags, topic or caption that point here


SHOP = ("google_shopping", "amazon", "pinterest")
MAPS = ("google_maps", "apple_maps", "osm", "maps_reviews")
MUSIC = ("spotify", "apple_music", "youtube_music", "youtube", "bandcamp")
WATCH = ("justwatch", "letterboxd", "imdb", "youtube_trailer")
READ = ("goodreads", "storygraph", "openlibrary", "bookshop")
WEB = ("official", "google", "wikipedia")

_TABS = [
    # design & style
    Tab("palette", "Palette", "palette", "each colour seen: name = a short colour name, value = its hex like #1a2b3c, detail = where it is used"),
    Tab("visual", "Visual", "notes", "what makes it look good: type, imagery, texture, mood; group = Type / Imagery / Mood"),
    Tab("structure", "Structure", "notes", "layout, grid, hierarchy and components; group = Layout / Hierarchy / Components"),
    Tab("style", "Visual language", "notes", "the style's name, era, influences and references; what to borrow; group = Style / Influences / Borrow"),
    Tab("borrow", "Borrow this", "checklist", "a concrete idea to reuse in your own work, as an instruction; at = when shown"),
    Tab("patterns", "Patterns", "cards", "each UI pattern or component shown: name = pattern, detail = how it is done here, at = when shown", providers=("google",)),  # Mobbin has no search URL (research, 14 Nov)
    Tab("motion", "Interactions", "notes", "each interaction or animation: name = what moves, detail = timing/easing/trigger, at = when shown"),
    Tab("made_with", "Made with", "cards", "each tool, plugin, font or kit used: name, detail = what it was used for", free="tools", providers=WEB),
    Tab("concept", "The idea", "notes", "the campaign or brand idea, audience, insight and why it works; group = Idea / Audience / Why it works"),
    Tab("copy", "Copy", "quotes", "each headline, tagline or line of copy, exactly as written: name = where it appears, value = the words, kind = quote"),
    Tab("tactics", "Tactics", "checklist", "each marketing tactic you could reuse, as an instruction"),
    Tab("pieces", "Pieces", "cards", "each item shown: name = the piece (brand and model if known), detail = colour, material, fit, amount = price if said", free="products", providers=SHOP),
    Tab("styling", "Styling", "notes", "how pieces are combined, proportions, occasions, care; group = How to wear / Occasions / Care"),
    Tab("materials", "Materials", "checklist", "each material, finish or part with amount = size or quantity", providers=SHOP),
    # travel & food
    Tab("places", "Places", "places", "each place: name = exact place name, detail = why go, group = city or area, amount = price level or cost", free="places", providers=MAPS),
    Tab("itinerary", "Itinerary", "timeline", "each stop in order: group = Day 1 / Morning, name = what to do, detail = tip"),
    Tab("plan", "Plan", "specs", "practical facts: name = Best time / Budget / Getting there / Stay / Visa / Tickets, detail = the answer from the post"),
    Tab("tips", "Tips", "notes", "each practical tip or warning from the post"),
    Tab("spots", "Spots", "places", "each restaurant, café, bar or stall: name, group = area, detail = what it is known for, amount = price", free="places", providers=MAPS + ("opentable",)),
    Tab("order", "What to order", "checklist", "each dish or drink to get: name, detail = where (spot name), amount = price"),
    Tab("ingredients", "Ingredients", "checklist", "each ingredient: name, amount = quantity with unit, group = part of the dish (Sauce, Dough)", free="ingredients", providers=("google_shopping",)),
    Tab("method", "Method", "steps", "each step in order: name = the instruction, at = when shown, amount = time it takes", free="steps"),
    Tab("swaps", "Swaps & notes", "notes", "substitutions, storage, make-ahead, dietary swaps; kind = swap / tip / storage"),
    Tab("equipment", "Equipment", "checklist", "each tool or piece of kit needed, also kit the frames clearly show", providers=SHOP),
    # tech & AI
    Tab("does", "What it does", "notes", "each thing the tool does or is good for, plainly; group = Does / Good for / Not for"),
    Tab("pricing", "Pricing", "specs", "each plan or price fact: name = plan, detail = price and limits"),
    Tab("alternatives", "Alternatives", "cards", "each alternative named in the post or comments: name, detail = how it differs", providers=("official", "alternativeto", "producthunt")),
    Tab("start", "Get started", "steps", "first steps to try it: name = the step, at = when shown", free="steps"),
    Tab("snippets", "Prompts & code", "quotes", "each prompt, command or code block shown or said: name = what it does, value = the exact text, kind = prompt / code / command"),
    Tab("setup", "Setup", "steps", "each setup step: install, config, keys; name = the step, value = command if any, at = when shown", free="steps"),
    Tab("repos", "Repos & docs", "cards", "each repository, package, model or docs page: name exactly as shown, detail = what it is", free="tools", providers=("github", "npm", "pypi", "huggingface", "google")),
    Tab("caveats", "Caveats", "notes", "limits, costs, risks or things that may be out of date"),
    Tab("specs", "Specs", "specs", "the product's own specs only (no prices: they go in buy): name = the spec (Battery, Weight), detail = the value as stated"),
    Tab("proscons", "Pros & cons", "proscons", "each pro or con from the post: name, kind = pro or con"),
    Tab("buy", "Where to buy", "cards", "each product to buy: name = brand and model, amount = price if said (every price goes here)", free="products", providers=SHOP + ("rtings",)),
    # music, film & books
    Tab("tracks", "Tracks", "cards", "each song or album: name = exact title, detail = artist, kind = song / album / playlist, at = when it plays", free="list_items", providers=MUSIC),
    Tab("artists", "Artists", "cards", "each artist or band: name, detail = genre or why mentioned", providers=("spotify", "apple_music", "wikipedia")),
    Tab("similar_music", "Similar music", "cards", "songs or artists the post itself suggests as similar; name = title, detail = artist; leave empty if the post names none", providers=MUSIC),
    Tab("titles", "Watch list", "cards", "each film or show: name = exact title, amount = year, kind = film / show / documentary, detail = why watch", free="books_media", providers=WATCH),
    Tab("people", "Cast & crew", "cards", "each actor, director or creator named: name, detail = role", providers=("imdb", "wikipedia")),
    Tab("similar_watch", "If you liked", "cards", "films or shows the post compares with; leave empty if none named", providers=WATCH),
    Tab("books", "Books", "cards", "each book: name = exact title, detail = author, amount = year, kind = book / audiobook", free="books_media", providers=READ),
    Tab("ideas", "Key ideas", "notes", "each core idea in one line"),
    Tab("quotes", "Quotes", "quotes", "each quote worth keeping, exactly as written or said: name = who said it, value = the quote, kind = quote, at = when said"),
    # life & how-to
    Tab("exercises", "Exercises", "checklist", "each exercise: name, amount = sets x reps or time, detail = rest or weight, group = block (Warm-up, Main), at = when shown", free="steps"),
    Tab("routine", "Routine", "timeline", "the weekly or session plan: group = Day or block, name = what to do"),
    Tab("form", "Form cues", "notes", "each form cue or safety point: name = exercise, detail = the cue"),
    Tab("advice", "Key advice", "notes", "each piece of advice in one line"),
    Tab("habits", "Habits", "checklist", "each habit or practice to try, as an instruction, amount = how often"),
    Tab("evidence", "Evidence & caveats", "notes", "what the advice rests on (studies, experts named) and its limits; kind = evidence / caveat; never add medical claims the post does not make"),
    Tab("steps", "Steps", "steps", "each step in order: name = the instruction, at = when shown", free="steps"),
    Tab("needs", "You'll need", "checklist", "each tool or material: name, amount = quantity or size", free="products", providers=SHOP),
    Tab("pitfalls", "Pitfalls", "notes", "mistakes to avoid and fixes"),
    Tab("when", "When & where", "event", "each event or deal: name, value = start date-time as YYYY-MM-DDTHH:MM if known, amount = price, group = place, detail = deadline or how to get in"),
    Tab("tickets", "Tickets & deals", "cards", "each ticket, offer or code: name, value = the code if shown, amount = price", providers=("official", "google")),
    Tab("prep", "Before you go", "checklist", "each thing to do or bring beforehand"),
    # news & learning
    Tab("glossary", "Glossary", "specs", "each term explained: name = term, detail = plain meaning"),
    Tab("deeper", "Go deeper", "cards", "each source, book, paper or topic the post points to: name, detail = what it covers", providers=("wikipedia", "youtube", "google_scholar")),
    Tab("quiz", "Quiz", "flashcards", "3 to 8 questions that test the key ideas: name = question, detail = the answer from the post"),
    Tab("claims", "Claims", "notes", "each claim made: name = the claim, kind = claim / opinion / prediction (fact only when the post cites evidence), detail = what it rests on"),
    Tab("sources", "Sources", "cards", "each source the post cites: name = title or outlet, detail = what it says", providers=("google", "google_news")),
    Tab("context", "Context", "timeline", "background events in order: group = date, name = what happened (from the post only)"),
    Tab("takes", "Other takes", "notes", "views the post itself mentions, rebuts or quotes from others; leave empty if none"),
    Tab("takeaways", "Takeaways", "notes", "each lesson in one line"),
    Tab("numbers", "Numbers", "specs", "each figure quoted: name = what it measures, detail = the number and period"),
    Tab("playbook", "Playbook", "checklist", "each action to take, as an instruction, in order"),
    Tab("companies", "Companies", "cards", "each company, product or person named: name, detail = role in the story", providers=WEB),
    Tab("positions", "Positions", "notes", "each side of the argument: group = the side, name = the point, detail = who argues it"),
    Tab("best", "Best replies", "quotes", "the most useful replies, exactly as written: name = who, value = the reply, kind = quote"),
    Tab("consensus", "Consensus", "notes", "where people agree and where they still disagree; kind = agree / dispute"),
]
TABS: dict[str, Tab] = {t.id: t for t in _TABS}

_CATEGORIES = [
    Category("design_inspiration", "Design inspiration", "design",
             "graphic design, art direction, posters, typography, illustration, visual references",
             ("visual", "palette", "structure", "style", "borrow"), "palette",
             ("What makes this layout work?", "Give me 3 ways to adapt this style for a poster", "Which fonts are close to this?"),
             types=("design",), formats=("showcase",),
             words=("poster", "typography", "typeface", "font", "graphic design", "illustration", "art direction", "layout", "moodboard", "editorial", "logo")),
    Category("ui_ux", "UI & product design", "design",
             "app and web interfaces, UX patterns, product design, interaction and motion design",
             ("patterns", "motion", "borrow", "palette", "made_with"), "patterns",
             ("Which of these patterns fit a settings screen?", "How would I build this interaction in CSS?", "What are the accessibility risks here?"),
             types=("design",),
             words=("ui", "ux", "interface", "app design", "web design", "figma", "dashboard", "onboarding", "micro-interaction", "microinteraction", "landing page", "design system", "component", "prototype", "framer")),
    Category("branding_marketing", "Branding & marketing", "design",
             "brand identities, campaigns, ads, copywriting, social media growth, packaging",
             ("concept", "copy", "tactics", "palette"), "tactics",
             ("Write 3 headlines in this style for my product", "Why does this campaign work?", "Which tactic is cheapest to try?"),
             words=("brand", "branding", "campaign", "ad ", "advert", "marketing", "copywriting", "packaging", "identity", "growth", "content strategy", "instagram growth")),
    Category("fashion", "Fashion & style", "design",
             "outfits, clothing, accessories, grooming and personal style",
             ("pieces", "styling", "palette"), "pieces",
             ("What could I swap for a cheaper piece?", "How do I wear this for a wedding?", "Which colours here suit warm skin tones?"),
             words=("outfit", "fashion", "style", "wardrobe", "ootd", "streetwear", "sneakers", "dress", "menswear", "womenswear", "capsule", "jacket", "grooming", "skincare")),
    Category("interiors", "Home & interiors", "design",
             "interior design, home decor, furniture, room makeovers, gardens",
             ("pieces", "palette", "materials", "styling"), "pieces",
             ("How would this work in a small flat?", "What is the cheapest piece to start with?", "Which paint colours are close?"),
             words=("interior", "home decor", "room", "living room", "bedroom", "kitchen design", "furniture", "apartment", "makeover", "renovation", "garden", "plants", "decor")),
    Category("travel", "Travel", "travel_food",
             "trips, destinations, itineraries, hotels, sights and travel tips",
             ("places", "itinerary", "plan", "tips"), "places",
             ("Plan 3 days from this", "When is the cheapest time to go?", "Which of these places are close together?"),
             types=("place",),
             words=("travel", "trip", "itinerary", "things to do", "visit", "hotel", "beach", "hike", "island", "city guide", "road trip", "flight", "airbnb", "destination", "hidden gem")),
    Category("food_places", "Restaurants & cafés", "travel_food",
             "restaurants, cafés, bars, street food and food guides to a place",
             ("spots", "order", "tips"), "spots",
             ("Which of these is best for a date?", "What should a vegetarian order?", "Which ones need booking?"),
             types=("place",),
             words=("restaurant", "cafe", "café", "coffee shop", "bar", "street food", "food tour", "brunch", "where to eat", "bakery", "pizza place", "michelin", "eatery", "food spot")),
    Category("recipe", "Recipes", "travel_food",
             "recipes, cooking, baking and drinks to make",
             ("ingredients", "method", "swaps", "equipment"), "ingredients",
             ("Scale this for 4 people", "Make this vegetarian", "What can I prep the day before?"),
             types=("recipe",),
             words=("recipe", "cook", "bake", "baking", "ingredients", "dinner", "lunch", "breakfast", "dessert", "sauce", "cocktail", "meal prep", "air fryer", "oven")),
    Category("software_tool", "Apps & software", "tech",
             "what an app, website, SaaS, extension or software tool is or does (not a how-to that only uses one)",
             ("does", "alternatives", "pricing", "start"), "alternatives",
             ("Is there a free alternative?", "How does it compare with what I use?", "What is the first thing to try?"),
             types=("tool",), formats=("review",),
             words=("app", "tool", "software", "saas", "extension", "website", "productivity", "notion", "plugin", "free tool", "mac app", "iphone app")),
    Category("ai_coding", "AI & code", "tech",
             "AI tools and prompts, coding tips, repositories, packages, developer workflows",
             ("snippets", "setup", "repos", "caveats"), "snippets",
             ("Turn this prompt into one for my use", "What do I need installed first?", "Explain this code line by line"),
             types=("tool",),
             words=("ai", "chatgpt", "claude", "gpt", "llm", "prompt", "agent", "code", "coding", "github", "python", "javascript", "api", "mcp", "cursor", "developer", "repo", "open source")),
    Category("gadgets", "Gadgets & products", "tech",
             "what a gadget, camera, phone, desk setup or other hardware is or does, and product reviews (fixing one is howto_diy)",
             ("specs", "proscons", "buy", "alternatives"), "buy",
             ("Is it worth it at this price?", "What is the main downside?", "What is a cheaper alternative?"),
             types=("tool",), formats=("review",),
             words=("gadget", "camera", "phone", "laptop", "headphones", "keyboard", "desk setup", "unboxing", "review", "tech review", "monitor", "watch", "speaker", "lens")),
    Category("music", "Music", "media",
             "songs, albums, artists, playlists, music recommendations and music production",
             ("tracks", "artists", "similar_music"), "tracks",
             ("Make me a playlist from this", "Who else sounds like this?", "What is this song about?"),
             list_kinds=("music",),
             words=("song", "music", "album", "playlist", "artist", "band", "track", "spotify", "vinyl", "beat", "producer", "dj", "lyrics", "concert", "remix")),
    Category("film_tv", "Film & TV", "media",
             "films, series, documentaries, anime, trailers and watch lists",
             ("titles", "people", "similar_watch"), "titles",
             ("Which one should I watch first?", "Where can I stream these?", "Which are good for a family night?"),
             list_kinds=("film", "show"),
             words=("movie", "film", "series", "tv show", "netflix", "documentary", "anime", "cinema", "trailer", "director", "season", "hbo", "a24")),
    Category("books", "Books & reading", "media",
             "books, reading lists, authors, book reviews and quotes from books",
             ("books", "ideas", "quotes"), "books",
             ("Which book should I start with?", "Summarise the main idea of each", "Which is the shortest read?"),
             list_kinds=("book",),
             words=("book", "books", "reading", "novel", "author", "booktok", "bookstagram", "kindle", "library", "chapter", "nonfiction", "fiction")),
    Category("fitness", "Fitness", "life",
             "workouts, exercises, training plans, running, yoga and sport",
             ("exercises", "routine", "form", "equipment"), "exercises",
             ("Make this a 20-minute version", "What can I do without equipment?", "How do I progress this each week?"),
             words=("workout", "exercise", "gym", "fitness", "training", "reps", "sets", "squat", "yoga", "pilates", "running", "abs", "stretch", "mobility", "hiit", "strength")),
    Category("wellbeing", "Health & wellbeing", "life",
             "health, nutrition, sleep, mental health, habits, motivation and life lessons",
             ("advice", "habits", "evidence", "quotes"), "habits",
             ("Turn this into a 7-day plan", "What is the evidence for this?", "Which habit is the easiest to start?"),
             words=("health", "sleep", "nutrition", "diet", "mental health", "anxiety", "habit", "habits", "wellness", "meditation", "motivation", "self improvement", "mindset", "therapy", "longevity", "life lesson")),
    Category("howto_diy", "How-to & DIY", "life",
             "how-tos, DIY, crafts, making, fixing or restoring things, cleaning, life hacks and practical skills",
             ("steps", "needs", "pitfalls"), "steps",
             ("What is the hardest step?", "Can I do this without the special tool?", "How long will this take?"),
             types=("howto",), formats=("tutorial",),
             words=("how to", "diy", "tutorial", "hack", "fix", "repair", "craft", "step by step", "cleaning", "organize", "organise", "sewing", "woodworking")),
    Category("events_deals", "Events & deals", "life",
             "events, launches, concerts, sales, deals, offers and deadlines with a date",
             ("when", "tickets", "prep"), "when",
             ("Remind me what I need before this", "Is this still on?", "What does it cost in total?"),
             words=("event", "festival", "sale", "deal", "discount", "promo code", "coupon", "tickets", "launch", "deadline", "giveaway", "conference", "meetup", "webinar", "limited time")),
    Category("learning", "Learning & explainers", "knowledge",
             "explainers, science, history, language learning, study tips and how things work",
             ("ideas", "glossary", "quiz", "deeper"), "quiz",
             ("Explain this like I'm 12", "Quiz me on this", "What should I read next?"),
             types=("explainer",), formats=("explainer", "reference"),
             words=("explained", "explainer", "science", "history", "how does", "learn", "physics", "biology", "psychology", "language", "study", "facts", "economics", "philosophy")),
    Category("news_opinion", "News & opinion", "knowledge",
             "news, current events, commentary, hot takes and opinion pieces",
             ("claims", "sources", "context", "takes"), "claims",
             ("Which claims are disputed?", "What happened before this?", "What would the other side say?"),
             types=("news_opinion",), formats=("news", "opinion"),
             words=("news", "breaking", "report", "election", "government", "policy", "opinion", "hot take", "announced", "lawsuit", "controversy")),
    Category("money_business", "Money & business", "knowledge",
             "personal finance, investing explainers, startups, careers, business and entrepreneurship",
             ("takeaways", "numbers", "playbook", "companies"), "playbook",
             ("What is the first step for me?", "Which numbers matter most here?", "What could go wrong?"),
             words=("money", "finance", "invest", "investing", "startup", "business", "founder", "revenue", "career", "salary", "budget", "side hustle", "saas growth", "entrepreneur", "marketing funnel", "job")),
    Category("discussion", "Discussions", "knowledge",
             "threads, Q&As, debates and posts whose value is in the replies",
             ("positions", "best", "consensus"), "consensus",
             ("What is the strongest argument on each side?", "Which reply is the most useful?", "Has this been settled?"),
             types=("discussion",), formats=("thread",),
             words=("thread", "reddit", "ask hn", "debate", "aita", "discussion", "what do you think", "unpopular opinion")),
    Category("other", "Other", "other", "anything else: humour, memes, personal moments, posts with no clear subject",
             (), "", ("What is this about?", "Why might I have saved this?")),
]
CATEGORIES: dict[str, Category] = {c.id: c for c in _CATEGORIES}
IDS = tuple(CATEGORIES)


def name(category: str) -> str:
    return CATEGORIES[category].name if category in CATEGORIES else ""


def tabs_for(category: str) -> list[Tab]:
    return [TABS[t] for t in CATEGORIES[category].tabs] if category in CATEGORIES else []


def check() -> list[str]:
    """Problems in the registry itself (a test runs this): unknown tabs, renders, sources, clashing ids."""
    problems = []
    for t in _TABS:
        if t.id in CORE:
            problems.append(f"tab {t.id} clashes with a core tab")
        if t.render not in RENDERS:
            problems.append(f"tab {t.id}: unknown render {t.render}")
        if t.free not in FREE_SOURCES:
            problems.append(f"tab {t.id}: unknown free source {t.free}")
    if len(TABS) != len(_TABS):
        problems.append("two tabs share an id")
    for c in _CATEGORIES:
        if c.group not in GROUPS:
            problems.append(f"{c.id}: unknown group {c.group}")
        for t in c.tabs:
            if t not in TABS:
                problems.append(f"{c.id}: unknown tab {t}")
        if c.tabs and c.lend not in c.tabs:
            problems.append(f"{c.id}: lends {c.lend}, which is not one of its tabs")
    return problems
