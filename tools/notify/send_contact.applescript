-- Send one iMessage to a person in Contacts, resolved at send time.
-- argv: 1 = contact name, 2 = message text. Both arrive as arguments, never spliced into this source.
-- The resolved number stays inside this script: it is never returned, printed or put in an error message.
on run argv
	set contactName to item 1 of argv
	set messageText to item 2 of argv
	tell application "Contacts"
		set matches to every person whose name is contactName
		if (count of matches) is 0 then error "contact not found" number 4101
		set phoneList to phones of item 1 of matches
		if (count of phoneList) is 0 then error "no phone" number 4102
		-- First mobile (or iPhone) number; otherwise the first number on the card.
		set targetHandle to value of item 1 of phoneList
		repeat with phoneEntry in phoneList
			set phoneLabel to label of phoneEntry
			if phoneLabel is not missing value then
				ignoring case
					if phoneLabel contains "mobile" or phoneLabel contains "iphone" then
						set targetHandle to value of phoneEntry
						exit repeat
					end if
				end ignoring
			end if
		end repeat
	end tell
	tell application "Messages"
		set targetAccount to 1st account whose service type = iMessage
		send messageText to participant targetHandle of targetAccount
	end tell
	return ""
end run
