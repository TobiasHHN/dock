// Ruhige Live-Anzeige (Task 3.F5, B7): reine Hilfen ohne React.

/** Stabile, gedeckte Farbe pro Person (für den Rand am Block, an dem sie gerade arbeitet). */
export function actorColor(key: string): string {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.codePointAt(0)!) >>> 0;
  return `hsl(${h % 360} 55% 48%)`;
}

/**
 * Wie weit muss gescrollt werden, damit der Ankerblock an derselben Bildschirmposition bleibt, wenn sich darüber
 * etwas ändert? Kleine Abweichungen (Rundung) und der Seitenanfang bleiben unberührt.
 */
export function scrollCorrection(oldTop: number, newTop: number, scrollY: number): number {
  const delta = newTop - oldTop;
  if (scrollY <= 0 || Math.abs(delta) < 2) return 0;
  return delta;
}
