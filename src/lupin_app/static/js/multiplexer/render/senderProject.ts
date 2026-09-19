/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
// The project a sender id names, shared by every surface that badges one.
//
// Ports legacy `getProjectFromSenderId` (notifications.js:15981): the upper-cased
// project of a `claude.code@<project>.deepily.ai[#session]` id, else "UNKNOWN".
//
// Extracted from NotificationsListRenderer.ts by parity A-2 #2m (row 2ebf322f),
// which needed the same parse for the Action Required card's [PROJECT] badge.
// One implementation, two readers — a second copy would drift the moment a
// sender-id shape changed, and only one of the two badges would follow it.

/* c8 ignore next */ // tsx phantom-branch artifact on the function declaration line (notificationItem.ts:46 precedent).
export function projectFromSenderId( senderId: string ): string {
  const project = senderId.match( /^claude\.code@([a-z][a-z0-9]*(?:-[a-z0-9]+)*)\.deepily\.ai/ )?.[ 1 ];
  return project === undefined ? "UNKNOWN" : project.toUpperCase();
}
