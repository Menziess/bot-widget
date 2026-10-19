// Which operating system is this? Returns "mac", "windows", "linux" or "other" (phone, tablet).
function detectOS(userAgent, platform) {
  var text = (platform + " " + userAgent).toLowerCase();
  if (/iphone|ipad|ipod|android/.test(text)) return "other";
  if (/mac/.test(text)) return "mac";
  if (/win/.test(text)) return "windows";
  if (/linux|x11|cros/.test(text)) return "linux";
  return "other";
}
if (typeof module !== "undefined") module.exports = { detectOS: detectOS };
