/**
 * Returns true when the page is running on a touch-first mobile device
 * (iPad, iPhone, Android tablet/phone).  Desktop browsers — even in
 * responsive DevTools mode — return false.
 */
export function isMobileDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  // maxTouchPoints > 1 catches iPad (which no longer says "iPad" in the UA)
  // and most Android tablets/phones.  We also keep the classic UA check as
  // a belt-and-suspenders fallback.
  const touchDevice = navigator.maxTouchPoints > 1;
  const mobileUA = /android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent);
  return touchDevice || mobileUA;
}
