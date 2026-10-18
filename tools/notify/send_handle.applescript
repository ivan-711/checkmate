-- Send one iMessage to a handle (phone number or Apple ID).
-- argv: 1 = handle, 2 = message text. Both arrive as arguments, never spliced into this source.
on run argv
	set targetHandle to item 1 of argv
	set messageText to item 2 of argv
	tell application "Messages"
		set targetAccount to 1st account whose service type = iMessage
		send messageText to participant targetHandle of targetAccount
	end tell
	return ""
end run
