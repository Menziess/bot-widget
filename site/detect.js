// Welk besturingssysteem is dit? Geeft "mac", "windows", "linux" of "other" (telefoon, tablet).
function detectOS(userAgent, platform) {
  var text = (platform + " " + userAgent).toLowerCase();
  if (/iphone|ipad|ipod|android/.test(text)) return "other";
  if (/mac/.test(text)) return "mac";
  if (/win/.test(text)) return "windows";
  if (/linux|x11|cros/.test(text)) return "linux";
  return "other";
}
if (typeof module !== "undefined") module.exports = { detectOS: detectOS };
