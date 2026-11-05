"""The help shown in the hub's help column and on the /help page (owner's decision, 24 Oct 2026): for each topic,
a few guides (short step lists that open in place) and the frequently asked questions. Plain words, written for
someone who is not technical. Kept as data so the page, the column and the tests read the same text."""

TOPICS = {
    "start": {
        "title": "Getting started",
        "guides": [
            ("Save your first post", "From your iPhone, in under a minute.", [
                "Open a post in Instagram, Threads, YouTube, Reddit, X or LinkedIn.",
                "Tap Share, then Magpiary (scroll the row of apps if you don't see it).",
                "You get one notification: “Saved to Magpiary”. Away from home it says it will send when you're home.",
                "Within a few minutes the post shows on the wall, with its video, transcript and summary."]),
            ("Add a post from the Mac", "Paste a link instead of sharing.", [
                "Copy the post's link.",
                "Press the + button at the top of the hub.",
                "Paste the link and press Add. It is read like any shared post."]),
            ("Find something again", "Search by what was said, shown or written.", [
                "Click the search at the top (or press /).",
                "Type a word that was said in the video, shown on screen, or written in the caption, or just "
                "describe the idea ('cheap places to eat').",
                "Word matches show at once; saves about the same idea join a moment later.",
                "Pick a result to open the post, or press Enter to see every match."]),
        ],
        "faqs": [
            ("What does Magpiary do with a post I share?",
             "Your Mac downloads it, keeps the video, writes down what was said (on the Mac), picks a few frames when the "
             "pictures matter, and files it on your wall. In Smart mode your AI key also writes a summary, key points, tags "
             "and the links it mentions."),
            ("Does anything go to a server?",
             "No server of ours exists. Your phone sends links straight to your Mac over Wi-Fi, and everything is "
             "kept in a folder on your Mac. In Smart mode, the caption, transcript and a few frames go to the AI service of "
             "your own key. The video never leaves the Mac."),
            ("Which apps can I share from?",
             "Instagram (reels and posts), Threads, YouTube (videos and Shorts), Reddit, X and LinkedIn. Other links are "
             "kept too, with what can be read from them. On the Mac, the Chrome extension saves any page you have open."),
            ("Do I need to keep the hub open?",
             "No. Magpiary runs in the background and starts when you log in. The hub is just a page to look at your "
             "library; close it any time."),
            ("Does it cost anything?",
             "Magpiary is free. Summaries use your own AI key: free keys from Google Gemini or OpenRouter work. In Private "
             "mode no key is needed at all."),
        ],
    },
    "library": {
        "title": "Your library",
        "guides": [
            ("Sort what you've saved", "Piles group related posts for you.", [
                "Switch the wall to Piles at the top.",
                "Open a pile to see what's in it; rename, merge or split it there.",
                "New saves join the pile they fit, or start a new one."]),
            ("Narrow the wall down", "Filters, tags and Select.", [
                "Press Filters to show only one source, one kind of post, posts with links, or posts that need you.",
                "Click a #tag on a post to see everything with that tag.",
                "Press Select to pick several posts and archive, tag or move them at once."]),
            ("Keep the wall tidy", "Archive and Trash.", [
                "Archive a post to take it off the wall; it stays searchable under Archive.",
                "Move a post to the Trash to remove it; it is deleted for good after 30 days.",
                "Share a post again to bring it back."]),
        ],
        "faqs": [
            ("Can I search for an idea, not a word?",
             "Yes. Search also finds saves about the same idea, even when they never use your words. It runs on this "
             "Mac with the same small model that makes piles, and uses no AI quota."),
            ("What's the difference between Archive and Trash?",
             "Archive keeps a post and its files, just off the wall, and search still finds it. Trash removes it: after 30 "
             "days the post and its files are deleted for good."),
            ("Why is a post in two places at once?",
             "It isn't stored twice. Sharing the same post again only counts it again; the wall shows it once."),
            ("What does “N new” on a pile mean?",
             "How many posts joined the pile since you last opened it."),
            ("Can I search what was said in a video?",
             "Yes. Search looks in the transcript, the words on screen, the caption and the summary, and shows the "
             "matching line on each result."),
            ("How do I change tile size or how piles look?",
             "In Settings → Appearance: tile size, tile labels, glass, interface size and page width. Changes show at once."),
            ("A post shows “Needs you”. What do I do?",
             "Open it: it says what went wrong in plain words (for example, the post is private or the site wants a login) "
             "and offers Try again. The Nest's “Needs you” tab lists them all."),
        ],
    },
    "piles": {
        "title": "Piles",
        "guides": [
            ("Fix a pile", "Rename, merge, split or remove.", [
                "Open the pile.",
                "Use Rename to give it a better name.",
                "Use Merge into to join it with another pile, or tick posts and Split off ticked to make a new pile."]),
            ("Start the piles over", "When the grouping no longer fits.", [
                "On the Piles view, press Regroup everything.",
                "Magpiary groups every post again, on this Mac, without using any AI quota."]),
        ],
        "faqs": [
            ("How are piles made?",
             "A small model on your Mac compares what each post is about and puts similar ones together. It runs on the "
             "Mac and uses no AI quota."),
            ("Can a post be in more than one pile?",
             "No: every save is in exactly one pile, so nothing gets lost between them."),
            ("Why did a post land in the wrong pile?",
             "Short or music-only posts give the model little to go on. Tick it on the pile page and split it off, or merge piles that belong together."),
        ],
    },
    "post": {
        "title": "A post",
        "guides": [
            ("Read a post quickly", "Summary, links, related, details.", [
                "Open a post from the wall.",
                "Summary has the caption, the key points and the moments worth jumping to.",
                "Links lists what the post mentions; Related shows similar saves; Details shows when and how it was read."]),
            ("Read a saved page, or keep it as a PDF", "For pages saved with Save what I see.", [
                "Open the post. A page saved from Chrome with Save what I see opens on its Read tab.",
                "It shows the page's words and pictures in their order, the way you saw them.",
                "Press Download PDF to keep a copy; it is made on this Mac.",
                "What I saw opens the picture of your screen taken when you saved it."]),
        ],
        "faqs": [
            ("What is Deeper dive?",
             "An extra, deeper reading of one post, on top of its normal summary, useful for long videos and podcasts. It runs only "
             "when you choose Deeper dive… in the post's menu. It needs Claude Code or Codex allowed in Settings → AI & digest, "
             "or a paid key; never a free key."),
            ("Why is there no summary?",
             "Either you're in Private mode, no AI key is added yet, or every key has reached its daily limit (it comes "
             "back tomorrow). The post is still searchable by what was said. Use Summarise again in the post’s menu once a key works."),
            ("A link is wrong. Can I fix it?",
             "Yes. Remove it from the Links tab, or add the right one by hand. Magpiary never brings back a link you removed."),
            ("Why is a post marked “Not related”?",
             "You told Magpiary it doesn't belong with another post. It won't show them together again."),
            ("Can I add my own notes and tags?",
             "Yes, on the post. They stay with it and are searchable."),
            ("The view and like counts look old.",
             "Press ↻ Refresh counts under the title to fetch the latest ones."),
        ],
    },
    "nest": {
        "title": "The Nest",
        "guides": [
            ("Pause and resume", "Each step has its own switch.", [
                "Open the Nest from the top bar.",
                "Use the switches for Transcribing, Summarising and Finding links.",
                "To try a new key on a few posts, choose “Only the next N, then pause” beside the switches."]),
            ("Clear what needs you", "Retry, connect, or remove.", [
                "Open the Nest's “Needs you” tab.",
                "Each row says why it stopped; press Try again, or open the post for more choices.",
                "“Try them all again” retries every summary that had a problem."]),
        ],
        "faqs": [
            ("Why are posts waiting?",
             "Magpiary reads one post at a time and fetches gently, so sites don't block it. Summaries also wait while a "
             "step is paused or every AI key has reached its limit."),
            ("What do the steps mean?",
             "Reading details (the caption and who posted it), Downloading (the video), Transcribing (what was said, on the "
             "Mac), Picking frames (stills when the pictures matter), Summarising (your AI key) and Finding links."),
            ("A post is stuck. What should I do?",
             "Open the Nest's “Needs you” tab. A site that asked to slow down is retried by itself later; a private or "
             "deleted post can't be fetched; a post that wants a login can be tried with your Instagram login."),
            ("Where do I see what came from my phone?",
             "The Nest's “From your phones” tab lists every share as it arrived, with its time and what happened to it."),
        ],
    },
    "ai": {
        "title": "AI & digest",
        "guides": [
            ("Get a free Gemini key", "About two minutes.", [
                "Open Settings → AI & digest and press Add a key.",
                "Pick Google Gemini and press “Open the Google Gemini page”.",
                "Sign in, press “Create API key”, and copy the key (it starts with “AIza”).",
                "Paste it and press Check and save. Magpiary tests it before keeping it."]),
            ("Use more than one key", "So summaries keep going when one runs out.", [
                "Add a second key (for example a free OpenRouter key).",
                "Use the ⋯ menu to move the key you prefer to the top.",
                "When the first key reaches its daily limit, the next one takes over, and the first comes back tomorrow."]),
            ("Switch to Private", "No AI at all.", [
                "Open Settings → AI & digest.",
                "Choose Private and confirm.",
                "New posts are still downloaded, transcribed, grouped and searchable, without summaries."]),
        ],
        "faqs": [
            ("What is sent to the AI?",
             "Only the caption, the transcript and a few frames of each post. The video itself never leaves your Mac."),
            ("Is a free key good enough?",
             "Yes. Free keys have a daily limit; Magpiary paces itself to stay within it and carries on the next day."),
            ("Does Google see my posts with a free key?",
             "With a free Gemini key, Google may use what is sent to improve its products. With billing turned on, Google "
             "says it does not. Private mode sends nothing."),
            ("What does “Limit reached · back tomorrow” mean?",
             "That key used its daily allowance. Summaries move to your next key, or wait until tomorrow if there isn't one."),
            ("What does “Refused” mean?",
             "The provider said the key is not valid any more (deleted, expired or blocked). Remove it and add a new one."),
            ("Can I pick the model?",
             "For OpenRouter, Claude and OpenAI keys, yes: use Change model in the key's ⋯ menu. Gemini picks the right one."),
            ("Why are summaries in English?",
             "So the library reads the same everywhere. Names and quotes stay as they were said."),
        ],
    },
    "agents": {
        "title": "AI agents",
        "guides": [
            ("Turn AI agents on or off", "Off until you switch them on.", [
                "Open Settings → AI agents.",
                "Turn on “Let AI agents use Magpiary”. Turn it off any time, and every Magpiary command and tool an AI uses stops at once.",
                "Under “What they may do”, switch off anything you do not want: reading your saves, saving links, or writing notes.",
                "“Recent activity” shows what they did, and Clear empties it. Under Advanced you can hide saves from them and set "
                "daily limits."]),
            ("Connect Claude Code or Codex", "One line in Terminal, once.", [
                "In Terminal, for Claude Code, run: claude mcp add magpiary -- magpiary mcp",
                "For Codex, run: codex mcp add magpiary -- magpiary mcp",
                "Optional, for Claude Code: run magpiary skill --install, so it knows when and how to use Magpiary.",
                "Start a new session, make sure AI agents are on in Settings, and ask “What did I save about…?”."]),
            ("Let an AI search your library", "Claude Code, Codex or any tool that can run commands.", [
                "Turn AI agents on in Settings → AI agents.",
                "In Terminal or in Claude Code or Codex, tell it: “Run magpiary help agents, then use those commands to look "
                "through my Magpiary saves.”",
                "Ask in plain words, such as “What did I save about sourdough?”. It runs magpiary search and magpiary show, "
                "and reads the answers.",
                "Reading works even when the hub is stopped, and it never changes your library."]),
            ("Let an AI save links and leave notes", "These two go through the running hub.", [
                "Make sure the hub is running and “Save links” or “Write notes” is on in Settings → AI agents.",
                "The AI runs magpiary add with a link, or magpiary note with a save's number and its note. The first time, Magpiary "
                "makes its key by itself.",
                "Its note shows on the post under your own, labelled with who wrote it. Remove it there any time.",
                "To undo a change, the AI can run magpiary note 12 --undo."]),
            ("Hide private saves from AI", "Tags they can never see.", [
                "Give the saves a tag, such as private, in the post's Tags box.",
                "Open Settings → AI agents → Advanced settings. Under “Hide from agents”, type that tag and tap Save.",
                "To an AI those saves do not exist: they are left out of search, lists, counts and notes."]),
        ],
        "faqs": [
            ("Which commands are there?",
             "magpiary search, show, list and status read your library. magpiary add saves a link and magpiary note writes a "
             "note. magpiary mcp is the connection for AI tools, and magpiary help agents lists everything. Add --json to "
             "any of them for a machine-readable answer."),
            ("What is the key?",
             "Saving links and writing notes use a small key that Magpiary makes the first time an AI does one of them. "
             "You never have to set it up. To stop them, switch off “Save links for me” or “Write notes on my saves”, or switch "
             "AI agents off. Reading does not need a key."),
            ("Can an AI delete or change my saves?",
             "No. The commands can find and read saves, save a new link, and write or remove its own note. They cannot delete, move, "
             "retitle or edit anything of yours, and they never touch your own note."),
            ("Does this use my AI quota?",
             "No. Nothing in these commands calls an AI. The AI you run them from does its own thinking on its own plan."),
            ("Where does what the AI reads go?",
             "The commands run on this Mac. What an AI reads is then part of its conversation, so it goes to the company behind that "
             "AI, like anything else you show it. Only give an AI access to your library if you are comfortable with that."),
            ("Does the switch lock my library?",
             "It controls what AI agents using Magpiary can do. Your library is a folder on this Mac, so it does not stop another "
             "program on the Mac from opening the files, the same as before."),
            ("A saved post says “ignore your instructions”. Is that a risk?",
             "Saved text comes from the internet, so every answer says to treat it as data, not instructions. A careful AI will; "
             "if you use an AI that does not, keep it to reading and do not let it act on what it reads."),
            ("Does it work from another device?",
             "Not yet. For now the commands work on this Mac only."),
        ],
    },
    "phones": {
        "title": "Saving posts",
        "guides": [
            ("Pair an iPhone", "One QR code, then a few “Allow” taps.", [
                "On the iPhone: Settings → Safari → Downloads → On My iPhone.",
                "On the Mac: Settings → Saving posts → Add a phone. Type its name. (Optional: a home Wi-Fi name, exactly as in "
                "the iPhone's Settings → Wi-Fi, if it should send only there.)",
                "Scan the QR code with the iPhone camera, then Get “Magpiary”, Download, and Add Shortcut.",
                "Open the Shortcuts app, tap Magpiary once, and tap Allow on every prompt. Never dismiss one."]),
            ("Send automatically when you get home", "A Wi-Fi automation, made once by hand.", [
                "In the Shortcuts app: Automation → New → Wi-Fi.",
                "Pick your home network, choose “Is Joined” and “Run Immediately”.",
                "Action: Run Shortcut → Magpiary, with no input. Turn off “Notify When Run”."]),
            ("Save from Chrome", "Pair the extension once, then one click.", [
                "Add the Magpiary extension to Chrome and pin it from the puzzle-piece menu.",
                "On the Mac: Settings → Saving posts → Chrome → Pair Chrome, and copy the code. It works once, for 15 minutes.",
                "Click the Magpiary icon in Chrome, paste the code and press Pair.",
                "From then on, open a page or post, click the Magpiary icon and press Save. Or right-click a page or a "
                "link and choose Save to Magpiary."]),
            ("Save what I see", "Keep a page exactly as it is on your screen.", [
                "Open the page in Chrome and click the Magpiary icon.",
                "Tick Save what I see, then press Save.",
                "Magpiary keeps the page's words and pictures as you see them, plus one picture of your screen.",
                "Open the post to read it on its Read tab, or download it as a PDF."]),
        ],
        "faqs": [
            ("I shared away from home. Is it lost?",
             "No. The phone keeps it and sends it when it is next on a Wi-Fi with your Mac, or when you tap Magpiary in the "
             "Shortcuts app."),
            ("The share said “The request timed out”.",
             "The Mac was asleep or off. The post is safe on the phone and goes out with the next share at home. Turn on "
             "“Keep awake while plugged in” to avoid it."),
            ("It says “This shortcut can't access…”.",
             "A permission prompt was dismissed. Open the Shortcuts app, tap Magpiary, and choose Allow on every prompt."),
            ("The share sheet froze for a few seconds.",
             "That sometimes happens in iOS. Wait a few seconds; the share completes and nothing is lost."),
            ("Which Wi-Fi name should I type?",
             "The exact name in the iPhone's Settings → Wi-Fi. The label at the top of the screen can be your phone "
             "company's instead."),
            ("What does Save what I see send, and where?",
             "Only when you tick it: the text and pictures of the page you have open, and a picture of the visible part of "
             "your screen. They go to Magpiary on this Mac and nowhere else. It works on pages you are signed in to, so "
             "what you can read is what is kept."),
            ("Why is Save what I see not in the panel?",
             "It shows on ordinary web pages. On a post from Instagram, Threads, YouTube, Reddit, X or LinkedIn, Magpiary "
             "reads the post itself, so the box isn't needed."),
            ("Can someone on my Wi-Fi pretend to be my phone?",
             "No. Since 0.1.5 the Shortcut never sends its key: it signs each send with it, and your Mac refuses a send that "
             "is unsigned, changed, or more than 10 minutes old. The links themselves still travel unencrypted on your Wi-Fi, so "
             "someone on the same network could see which links you send. A phone set up before 0.1.5 is marked in Settings → "
             "Saving posts until you install its new Shortcut."),
            ("Can I use the hub from my phone?",
             "Not yet: the hub only opens on this Mac. Opening it from your phone is planned for later."),
            ("Do I need a new code for a new phone?",
             "Yes, each phone gets its own. “New install code” in a phone's ⋯ menu replaces that phone's key; its Shortcut "
             "then needs installing again."),
        ],
    },
    "links": {
        "title": "Links and web search",
        "guides": [
            ("Add a free web search key", "Finds the sites the free directories miss.", [
                "Open Settings → AI & digest → Finding links → Add a search key.",
                "Pick Tavily (free, no card, 1,000 searches a month) and open its page.",
                "Sign up, copy the key, paste it and press Check and save."]),
            ("Connect your Instagram login", "Only for posts that need one.", [
                "Open the Terminal app and run: magpiary login connect",
                "Allow both macOS prompts (Terminal using other apps' data, and “Chrome Safe Storage”).",
                "Reload Settings. On a blocked post, press “Try with my Instagram login”."]),
        ],
        "faqs": [
            ("How are links found?",
             "First the addresses the post itself gives, then free directories (Wikidata, GitHub, the App Store, "
             "Wikipedia, OpenStreetMap, Crossref), then a web search if you added a key. Each site is opened to check it fits."),
            ("Does finding links use my AI quota?",
             "No. It never uses your AI keys."),
            ("Why does a big brand have no link?",
             "Names mentioned in passing (Instagram, Google, a big brand) get no link, so the list stays useful."),
            ("Is fetching with my Instagram login safe?",
             "It carries a small risk to your account, so Magpiary only uses it when you press the button on a blocked post. "
             "It is never used for normal fetching."),
            ("How do I stop using my Instagram login?",
             "Settings → Saving posts → Instagram login → Disconnect. Magpiary deletes its copy."),
        ],
    },
    "digest": {
        "title": "Digest",
        "guides": [
            ("Read your digest", "What you saved, what it was about, and what's worth doing.", [
                "When a new digest is ready, a banner shows on the wall, the Digest button in the top bar gets a pink dot, "
                "and your Mac shows a notification.",
                "Click Digest. The words under “In your words” are what your saves were about; click one to see its saves.",
                "From the top: the numbers, the standout, three things worth doing with why each was picked, and the themes.",
                "You can reopen it any time with the Digest button. Only the newest digest is shown."]),
            ("Steer the picks", "Tell Magpiary what you're working toward.", [
                "Open Settings → AI & digest → Digest.",
                "Write a line or two under My goals and press Save.",
                "The next digest's 'Worth doing' picks lean toward them."]),
        ],
        "faqs": [
            ("When does a digest arrive?", "Monthly on the 1st at 9:00 by default. In Settings → AI & digest → "
             "Digest you can choose weekly, or both. If the Mac is asleep then, it's made as soon as the Mac wakes."),
            ("Why doesn't the notification open the hub?", "macOS shows it through its Script Editor, so clicking it "
             "can't open the hub. Open the hub yourself; the Digest button's dot shows where to look."),
            ("Who writes it?", "The first one ready in Settings → AI & digest → AI keys: Claude Code or Codex (once you allow "
             "them there) or a paid key. With only free keys the Digest is off, unless you turn it on anyway. In Private "
             "mode there's no written part, only the words, numbers and piles."),
            ("A period with no saves?", "It's kept quietly, with no dot and no notification."),
        ],
    },
    "boards": {
        "title": "Shared boards",
        "guides": [
            ("Make a board and fill it", "Inside Library, next to Piles and Everything.", [
                "Open Library → Boards, name a board and press New board.",
                "Press Add posts on the board, tick posts from your library and press Add to the board. Or right-click "
                "a post (or select several) and choose Add to board.",
                "Vote 👍 or 👎 on any card. A pink ring means more than one of you added it.",
                "Click a card to read it, open the post, or take your own card off the board."]),
            ("Share to a board from your iPhone", "The same Share → Magpiary, with one question.", [
                "Tap Share → Magpiary as usual.",
                "While a board is active (made or changed by anyone in the last 7 days), Magpiary asks "
                "“Add it to a board too?”. Tap Just my library, or a board.",
                "No active board: no question, it goes straight to your library.",
                "A quiet board comes back as soon as anything changes on it, on the phone after its next send at home."]),
            ("Invite a friend", "They need Magpiary on their own Mac.", [
                "Open the board and press Invite: the board's code shows at once.",
                "Press Share… (Messages, WhatsApp, Mail, AirDrop) or Copy message. The same code works for everyone "
                "you send it to, for 7 days; then Invite makes a new one.",
                "Someone you've shared a board with before: press Invite next to their name instead. It shows up in "
                "their Magpiary after their next sync, with Join and Not now.",
                "They click the link on their Mac, or type the code under Library → Boards, and press Join."]),
            ("Use your own Backblaze bucket", "Dependable sync, free up to 10 GB.", [
                "Open backblaze.com → B2 Cloud Storage → Sign up, and confirm your email. Pick the region closest to you; "
                "it can't change later.",
                "In the left menu, open Application Keys and click Generate New Master Application Key.",
                "Copy the keyID and the applicationKey (shown only once).",
                "In Magpiary: Settings → Shared boards → Where boards sync → Connect Backblaze B2. Paste both and press "
                "Connect. Magpiary makes a private bucket and checks it can write, read and remove."]),
            ("Use Cloudflare R2 instead", "Free up to 10 GB; Cloudflare asks for a card.", [
                "In the Cloudflare dashboard, open R2 and create a bucket.",
                "Under R2 → Manage API tokens, create a token with Object Read & Write, limited to that bucket.",
                "Copy the Access Key ID, the Secret Access Key and the S3 address (https://….r2.cloudflarestorage.com).",
                "In Magpiary: Settings → Shared boards → Where boards sync → Connect Cloudflare R2 or another. Fill "
                "them in with the bucket's name and press Connect."]),
        ],
        "faqs": [
            ("What are shared boards?", "You and friends who run Magpiary fill a board together, for a trip or anything "
             "else. Each of you adds posts, and everyone's board shows who added what, with votes."),
            ("Nostr relays or my own bucket?", "Relays need nothing from you and are the default. They're run by "
             "volunteers and may drop old posts, so a group that wants dependable sync can use one person's bucket. "
             "Either way, everything is sealed on your Mac first: the relay or storage service can't see what's in it."),
            ("What happens when someone is removed?", "Only the board's creator can remove a member. Their cards and "
             "votes leave the board, their bucket key is deleted, and the board gets a new key that only the remaining "
             "members receive, so they can't read what's added next. Cards that already reached their Mac stay there."),
            ("Why should the invite code stay private?", "Anyone with the code can join the board until it runs out, and "
             "read and add to it. Send it only to the people you want; if it went further, press New code, and remove "
             "anyone who shouldn't be there."),
            ("Can friends invite others?", "On a board that syncs through Nostr relays, any member can. On a board in "
             "your own bucket, only you can, since it makes a key for each friend. With Cloudflare R2, friends share "
             "your bucket key, so removing someone from an R2 board means making a new key in Cloudflare."),
            ("Does a post shared to a board also go in my library?", "Yes. It's read on your Mac like any save, and "
             "goes on the board once it's ready, with its summary and picture."),
            ("Why doesn't my phone show a new board?", "The phone keeps a copy of the board list, refreshed each time it "
             "sends at home. Share anything at home (or let the Wi-Fi automation run) and it appears."),
            ("Who pays for the bucket?", "The person who connects it. Backblaze is free up to 10 GB, far more than "
             "boards need: a card is a few KB."),
        ],
    },
    "profile": {
        "title": "Your profile",
        "guides": [
            ("Set up your profile", "How friends see you on boards.", [
                "Open Settings → Your profile.",
                "Type your name and press Save. Choose a photo, frame it in the circle, and pick a colour.",
                "Add a line about you and any links you want to show. Only what you fill in is shown.",
                "Check the preview at the top: that is what a friend sees when they click your face on a board."]),
            ("Change the topics on your profile", "They follow your piles.", [
                "Open Settings → Your profile → Topics.",
                "The topics come from your biggest piles and update as your library changes.",
                "Press × to take one off, or type your own and press Add.",
                "To bring back a topic you took off, type its name and press Add."]),
        ],
        "faqs": [
            ("What do friends see?", "Your name, photo, colour, about line, links and topics, and the posts you add to a "
             "board you share with them. Only people on a board with you can open your profile. The rest of your "
             "library stays private."),
            ("Where do my topics come from?", "From the names of your biggest piles, so they stay up to date. Take off "
             "any you don't want to show."),
            ("What is my key?", "A secret made on this Mac that signs what you add to a board, so nobody can act as you. "
             "It never leaves this Mac. Your short ID is its public part, so friends can tell two people with the same "
             "name apart."),
            ("Does my photo keep where it was taken?", "No. It's re-made at 256 px on this Mac, without its location, "
             "date or camera details."),
            ("Do my changes reach friends?", "Yes, at the next sync. Name, photo, about and links go out at once; topics "
             "that only follow your piles go out at most once an hour."),
        ],
    },
    "storage": {
        "title": "Library & this Mac",
        "guides": [
            ("Open your files", "Everything is in folders you own.", [
                "Open Settings → Library & this Mac.",
                "Press Show in Finder next to Library, Notes or Models.",
                "Notes are Markdown files; open the folder in Obsidian to browse them there."]),
            ("Back up and restore", "A copy of your library, made in one press.", [
                "Open Settings → Library & this Mac.",
                "Press Back up now to make a copy.",
                "To go back to an earlier copy, use Restore from a backup in the same place."]),
            ("Free up space", "Empty the Trash.", [
                "Open Settings → Library & this Mac.",
                "Press Empty next to the Trash, and confirm.",
                "The posts and their videos are deleted for good."]),
        ],
        "faqs": [
            ("Where is my library?",
             "In a Magpiary folder in your home folder: the database, the archived videos and photos, and a Markdown note "
             "per post."),
            ("Can I back it up?",
             "Yes: Settings → Library & this Mac → Back up now, or back up the Magpiary folder with Time Machine. It holds "
             "everything."),
            ("What are the models?",
             "The speech model that writes down what was said, and a small model that finds related posts and piles. "
             "Both run on the Mac."),
            ("How do I remove Magpiary?",
             "In Terminal, run magpiary uninstall. Your library stays unless you add --delete-library."),
        ],
    },
    "appearance": {
        "title": "Appearance",
        "guides": [
            ("Make it yours", "Theme, tiles, glass, size and width.", [
                "Open Settings → Appearance.",
                "Pick a theme (Indigo or Dark), a tile size and tile labels; changes show at once.",
                "Turn glass on or off, and make the whole interface smaller or bigger with Interface size.",
                "On a large screen, pick a page width, or Full width."]),
        ],
        "faqs": [
            ("Why doesn't the page width change?",
             "A width only shows when the window is wider than it. On a laptop, 1,600 px is the one that makes a difference."),
            ("Is there a light theme?",
             "Not yet. Indigo and Dark are the two looks for now."),
        ],
    },
    "ask": {
        "title": "Ask Magpiary",
        "guides": [
            ("Turn Ask on", "Questions about your saves, answered from them.", [
                "Open Settings → Ask Magpiary and turn on Use Ask Magpiary.",
                "It needs an AI key, or Claude Code or Codex allowed in Settings → AI & digest → AI keys.",
                "Choose who answers under Who answers, and whether it may search the web."]),
            ("Ask a question", "About a post, a pile, a board or everything.", [
                "Press Ask Magpiary at the bottom right of any page.",
                "Ask in plain words, such as “Which of my saves are about sourdough?”.",
                "The answer lists the posts it came from; click one to open it."]),
        ],
        "faqs": [
            ("What is sent when I ask?",
             "Your question, the saves it needs to answer and your goals go to whoever answers: your AI key's service, or "
             "Claude Code or Codex on your own plan. Nothing is sent until you ask."),
            ("Does it use my AI quota?",
             "Yes, each answer uses tokens from whoever answers. Settings → Ask Magpiary shows the tokens used today, this "
             "week and this month, and can set a limit."),
            ("What happens to my chats when I turn Ask off?",
             "Every Ask button goes and any answer being written stops. Your chats are kept for when you turn it back on."),
        ],
    },
    "privacy": {
        "title": "Privacy",
        "guides": [
            ("See what leaves this Mac", "One page, every item.", [
                "Open Settings → Privacy.",
                "“What leaves this Mac” lists each thing, exactly what goes and where, and whether it is on."]),
            ("Lock the hub with a PIN", "Keep visitors out while your Mac is unlocked.", [
                "Open Settings → Privacy → Hub lock and choose a 6-digit PIN.",
                "Open tabs cover themselves when the Mac sleeps or locks, after your idle time, or when you press Lock.",
                "Optional: add Touch ID in each browser you use, on the same localhost address Magpiary opens at."]),
            ("macOS permission prompts", "Every one Magpiary can cause, and why. Each is asked once.", [
                "“Magpiary would like to access data from other apps” or “manage apps”: the first time you press Download PDF, "
                "or Magpiary reads a page that needs a browser to draw it. It runs Chrome (or Chromium, Edge, Brave) in the "
                "background with an empty profile; it never opens your own Chrome profile. Allow it, or PDFs fall back to "
                "your browser's Save as PDF.",
                "“Accept incoming network connections?”: only when the macOS firewall is on. Allow it so your iPhone can "
                "send saves over Wi-Fi.",
                "Notifications from “Script Editor”: the note that a new digest is ready. macOS names the tool Magpiary uses "
                "to show it; turning it off only hides the note.",
                "Terminal using other apps' data, and “Chrome Safe Storage”: only when you run magpiary login connect, to "
                "copy one site's login.",
                "The prompts say Magpiary with its icon. On a Mac without Apple's command line tools they say Python 3.12 "
                "instead; it is the same request. Change your answer any time in System Settings → Privacy & Security."]),
        ],
        "faqs": [
            ("Why did a prompt say Python 3.12?",
             "Magpiary is written in Python. Since 0.1.5 it runs inside a small Magpiary launcher so prompts name Magpiary; "
             "if Apple's command line tools are missing it runs without it and macOS names Python. What you allowed for "
             "Python 3.12 is asked once more for Magpiary."),
            ("I forgot my PIN.",
             "Run magpiary lock reset in Terminal. It turns the lock off and forgets the PIN and every Touch ID; your library "
             "and boards are untouched."),
            ("Is the lock encryption?",
             "No. It keeps casual visitors out of the hub. Anyone signed in to your Mac account can still read the ~/Magpiary folder."),
            ("Does the lock stop my phone?",
             "No. Sharing from your phone, the pipeline and board sync keep running while the hub is locked."),
            ("Is there telemetry?",
             "No. Magpiary sends no usage data and has no account and no server."),
            ("Where are my keys kept?",
             "In ~/.config/magpiary/keys.json on this Mac, readable only by you. They are never shown again after you save them."),
            ("How do I delete my data?",
             "Settings → Privacy → Delete my data: forget the Instagram login, remove all keys, empty the Trash, or remove "
             "everything with magpiary uninstall --delete-library."),
        ],
    },
}

# Which topic the help column shows on each page (Settings uses its section name).
PAGE_TOPIC = {"wall": "library", "search": "library", "shelf": "library", "add": "start", "welcome": "start",
              "pile": "piles", "card": "post", "related": "post", "nest": "nest", "doctor": "nest", "digest": "digest"}

# What's new, shown once after an update (newest first). Plain words; one line each.
CHANGES = [
    ("0.1.5", ["Save what I see: tick it in the Chrome extension to keep a page as it is on your screen, signed-in pages included.",
               "Saved pages open on a Read tab with their words and pictures in order, and download as a PDF in one click.",
               "Posts from any website show that site's name and icon.",
               "macOS permission prompts name Magpiary, and Help lists every prompt and why.",
               "A clearer Help page: chapters on the left, and a guide for Ask Magpiary and the Chrome extension."]),
    ("0.1.4", ["A new welcome guide: save from Chrome or your iPhone, skip any step, and watch each step tick off as Magpiary sees it happen.",
               "Chrome can tell Magpiary it is installed and pinned (with the newer extension), and the iPhone step now ticks only when the phone has really reached your Mac.",
               "“Send when I get home” moved to Settings.",
               "Round-up posts keep every thing they recommend, each with its own link: videos, articles, books and shows.",
               "Web pages give their whole text and pictures, not just a preview line.",
               "Each post shows its shape and topic (List · product design), and suggested tags reuse yours.",
               "Videos over 20 minutes wait for Read it now; a video's own chapters become its key moments.",
               "Threads videos are saved and play again, and a busy AI key hands the post to your next key.",
               "Search understands what you ask for."]),
    ("0.1.3", ["Each Mac account now has its own Magpiary and its own library, so two accounts on one Mac no longer meet.",
               "The steps for getting an AI key are bigger and clearer, with the link first."]),
    ("0.1.2", ["The library opens only after setup has finished; clicking the Dock icon during setup shows the download again.",
               "A redesigned disk image with an Open Anyway guide, and a one-line Terminal install that skips the macOS warning.",
               "Retry with my login now works for any site that refuses, and Settings can restore your library from a backup.",
               "A redesigned digest page and a steadier Find the link."]),
    ("0.1.1", ["The first-run window opens at once and shows the downloads as they happen.",
               "A smaller interface on laptop screens, with an Interface size setting in Appearance.",
               "Saving a Gemini key no longer waits on a busy model, and each key form shows its own guide.",
               "The Chrome extension can be added from Settings, and shows a success screen once paired.",
               "Add to note puts the answer in your note straight away, and pages show a loading line while they open."]),
    ("0.1.0", ["Search finds saves by idea as well as by word.",
               "A monthly digest: what your saves were about, and three things worth doing.",
               "Settings in two columns, with a help column and a Privacy page.",
               "Appearance shows pictures for each choice, and one Page width control.",
               "The summary limit and summaries that had a problem now live in the Nest."]),
]

# How each topic looks: its colour, icon and one line for the header card (the UI pass, 24 Oct 2026).
LOOK = {
    "start": ("var(--t-howto)", "book", "The basics: saving, adding and finding posts."),
    "library": ("var(--t-explainer)", "library", "The wall, search, filters, Archive and Trash."),
    "piles": ("var(--t-design)", "grid2", "How posts are grouped, and how to fix a pile."),
    "post": ("var(--t-tool)", "summary", "Summaries, links, related posts and your notes."),
    "nest": ("var(--t-discussion)", "moon", "What Magpiary is doing, and what is waiting or stuck."),
    "ai": ("var(--t-design)", "sparkle", "Keys, limits, modes, and what is sent."),
    "agents": ("var(--t-tool)", "terminal", "Let an AI search your saves, save links and leave notes."),
    "ask": ("var(--t-design)", "comment", "Ask questions about your saves, answered with the posts they came from."),
    "phones": ("var(--t-howto)", "phone", "Your iPhone and Chrome, and getting posts home."),
    "links": ("var(--t-explainer)", "links", "How links are found, search keys and Instagram."),
    "digest": ("var(--t-design)", "digest", "What you saved, what it was about, and what's worth doing."),
    "profile": ("var(--t-place)", "people", "How friends see you, and what they can open."),
    "boards": ("var(--t-news_opinion)", "folder", "Boards you share with friends, and where they sync."),
    "storage": ("var(--t-discussion)", "folder", "Your files, the Trash, and removing Magpiary."),
    "appearance": ("var(--t-tool)", "palette", "Theme, tiles, glass, size and width."),
    "privacy": ("var(--fg-2)", "lock", "What leaves this Mac, and how to delete your data."),
}
GUIDE_ICONS = {
    "Save your first post": "phone", "Add a post from the Mac": "plus", "Find something again": "search",
    "Sort what you've saved": "grid2", "Narrow the wall down": "filter", "Keep the wall tidy": "trash",
    "Fix a pile": "summary", "Start the piles over": "clock", "Read a post quickly": "frames",
    "Pause and resume": "moon", "Clear what needs you": "alert", "Get a free Gemini key": "sparkle",
    "Use more than one key": "links", "Switch to Private": "lock", "Pair an iPhone": "phone", "Turn AI agents on or off": "sliders",
    "Hide private saves from AI": "lock", "Let an AI search your library": "terminal", "Connect Claude Code or Codex": "links",
    "Let an AI save links and leave notes": "plus", "Save from Chrome": "ext", "Save what I see": "eye",
    "Read a saved page, or keep it as a PDF": "openpage", "Back up and restore": "archive", "Turn Ask on": "sliders",
    "Ask a question": "comment", "Change the topics on your profile": "sliders", "Lock the hub with a PIN": "fingerprint",
    "macOS permission prompts": "info",
    "Send automatically when you get home": "download", "Add a free web search key": "search",
    "Connect your Instagram login": "check", "Open your files": "folder", "Free up space": "trash",
    "Make it yours": "palette", "See what leaves this Mac": "lock", "Read your digest": "digest",
    "Steer the picks": "sparkle", "Set up your profile": "people", "Use your own Backblaze bucket": "folder",
    "Use Cloudflare R2 instead": "folder", "Invite a friend": "people", "Make a board and fill it": "plus",
    "Share to a board from your iPhone": "phone",
}
# The /help page's chapter list, in reading order: (heading, topics). Every topic is in exactly one group.
HELP_GROUPS = (
    ("Using Magpiary", ("start", "phones", "library", "post", "piles", "nest")),
    ("AI", ("ai", "digest", "ask", "links", "agents")),
    ("With friends", ("boards", "profile")),
    ("This Mac", ("storage", "appearance", "privacy")),
)
GUIDE_TINTS = ("var(--t-howto)", "var(--t-design)", "var(--t-explainer)", "var(--t-discussion)", "var(--t-tool)")
