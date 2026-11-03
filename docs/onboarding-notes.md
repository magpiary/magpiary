# Magpiary onboarding notes (raw material for the setup guide and installer)

Everything here was learned on the owner's iPhone and Mac during M0 (22 Oct 2026) and is the source for the user-facing guide. Turn it into steps a non-technical person can follow, and make the installer check what it can.

## The phone, in order
1. **Safari downloads must go to "On My iPhone".** Settings, Safari, Downloads, On My iPhone. If iCloud is full, the downloaded Shortcut shows "Error" and never installs.
2. **Install by scanning the QR code** shown on the Mac's setup page (only visible on the Mac; the code expires after 15 minutes). Camera, tap the banner, tap **Get "Magpiary"**, **Download**, open it from Safari's downloads, **Add Shortcut**. One-tap install is not possible yet (it needs https).
3. **Run Magpiary once from the Shortcuts app** (tap its tile) and tap **Allow / Always Allow** on every prompt: notifications, access to **On My iPhone**, connect to the Mac (`<name>.local`), send items to the local address. Do this *before* the first share from another app. **Never dismiss a prompt**: that causes "This shortcut can't access ... change this in Shortcuts privacy settings".
4. **The first one or two shares from Instagram may ask again**, even after step 3, and one first share froze (stuck at about 10 to 15%, then an "XPC error" notification). Fix: tap Allow each time; if it freezes, stop it (the square in the Dynamic Island), close the Shortcuts app and the other app, and share again. After that it was stable: three more shares in a row, one notification each, no prompts.
5. **There is no folder to create.** The queue is a single file, `magpiary-outbox.txt`, at the top of On My iPhone. (A `Magpiary/queue` folder had to be created by hand and fails if missing; a Shortcut does not create folders; leaving the folder out fails too.)
6. **Wi-Fi automation is made by hand** (iOS cannot generate or share automations): Shortcuts, Automation, new, **Wi-Fi**, pick the **home network**, **Is Joined** only, **Run Immediately**, action **Run Shortcut: Magpiary** with no input. Turn off "Notify When Run" for a quiet setup (otherwise iOS shows a banner each time).
7. **Pick the real network name.** The label in the status bar can be the carrier's (it said "Carrier WiFi" while the network is "Example Wi-Fi"). The Shortcut only sends on the network name baked in at install (`--home-wifi`).
8. **Changing a Shortcut's name or folder means reinstalling it** and redoing steps 3 and 6.

## What the user should expect
- **Exactly one notification per share.** At home: the Mac's message ("Saved to Magpiary", "Already in Magpiary"). Away from home or Mac off: "Saved. It will send when you're home." If the Mac refuses (wrong key, error): "Saved on your phone. The Mac didn't accept it yet." Nothing is lost in any of those cases.
- Sharing the same item again counts it again (saved 3 times) but stores it once.
- Away from the Mac, on mobile data, the Shortcut does not try to send (no long timeout); it sends when the Wi-Fi automation fires.

## The Mac
- The phone and Mac must be on the same network; the phone reaches the Mac by its Bonjour name (`<name>.local`), plain http, with a pairing key baked into the Shortcut.
- If the macOS firewall is on, it will ask to allow incoming connections (not yet tested; it was off).
- Pairing (Settings → Phones, or the first-run guide) is served only to the Mac itself; the personalised Shortcut is served behind a short-lived token.

## Known limits to say plainly
- A failed connection stops the Shortcut and iOS shows its own error; it cannot be caught.
- Only one iOS version and one phone were tested.
- Instagram, Threads, YouTube (videos and Shorts), Reddit, X and LinkedIn shares from their own apps were all tested on one phone on 23 Oct and arrived.
- Mac asleep, screen-locked automation, and a Mac with the firewall on are untested.

## Delayed delivery (found 23 Oct)
If Wi-Fi is switched off and straight back on, the automation may not fire (iOS may not count a quick reconnect as joining). Nothing is lost: the reels wait on the phone and go out at the next real join of the home Wi-Fi, or when the user taps Magpiary in the Shortcuts app. The automation does run with the phone locked.

## Automation switch: "Run After Connection Interruption" (decided 23 Oct: leave OFF)
In the Wi-Fi automation this switch is off by default and we keep it **off**. the owner chose this because a Wi-Fi drop would keep triggering runs. Consequence, to say plainly in the guide: if Wi-Fi is switched off and straight back on, a waiting reel is not sent at once; it goes out at the next real join of the home Wi-Fi, or when the user taps Magpiary in the Shortcuts app (nothing is lost). "Confirm Before Run" stays off. We did not test whether turning the switch on fixes the delay.

## Mac asleep (found 23 Oct)
If the Mac is asleep, a share from the phone waits about a minute and iOS then says "The request timed out." The reel is saved on the phone and goes out later: wake the Mac and tap Magpiary in the Shortcuts app (or rejoin the home Wi-Fi). **No manual step is needed afterwards**: the next share (or the Wi-Fi automation) sends everything that is waiting, verified with 2 timed-out shares followed by 1 successful share (3 reels, one batch, each stored once). To avoid the wait, the Mac must stay reachable: the installer should offer to keep the Mac awake while it is plugged in (and explain the option "Wake for network access" in System Settings, which is off on the owner's Mac), and never block on battery.

## Share sheet pause (found 23 Oct)
Sometimes the iOS share sheet freezes for about 5 seconds, with nothing shown, then the share completes. Nothing is lost. Say so in the guide: wait a few seconds. Cause not known.

## Mobile data test (23 Oct)
5 shares away from home (one a repeat) were sent by the Wi-Fi automation on rejoining home Wi-Fi, without opening the Shortcuts app.

## The Mac side: background service (23 Oct)
`magpiary service install` makes the receiver start at login and restart if it stops; `magpiary service status` shows whether it is running; `magpiary service uninstall` removes it. The installer must put the program somewhere outside Documents, Desktop and Downloads (macOS will not let a background service read files there), for example with `uv tool install`. The log is `~/Library/Logs/Magpiary/receiver.log`.

## Home Wi-Fi name
The user types it at setup, using the exact name in the iPhone's Settings, Wi-Fi (not the status-bar label). The Mac cannot suggest it: macOS hides the network name from programs.

## LinkedIn
LinkedIn shares a short `lnkd.in` link; the Mac turns it into the full post link on its own.

## Check at the fresh-install walk-through
- The privacy sentences in the setup step "How should posts be read?" (Smart sends the caption, transcript and a few frames to your AI; the video file stays on the Mac; Private sends nothing to any AI). Added 28 Oct; not yet seen by a new user. Check they read clearly and do not worry people.
- Delivery states on the wall tile ("Received · waiting its turn", "Reading it · …"); the "Waiting on the phone" state still needs the phone side (plan item 2.5).
