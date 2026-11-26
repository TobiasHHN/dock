// Geführte Übung im Dokument: hebt echte Elemente der Oberfläche hervor, erklärt sie in einer Karte daneben
// und meldet, sobald der Nutzer die Aufforderung ausgeführt hat. Die Seite bleibt dabei bedienbar.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Icon } from "../ui/icons";
import { Visual } from "./TourVisuals";
import { type Box, GUIDE_STEPS, placeCard } from "./tourModel";
import { closeTour, setGuideStep, useTour } from "./tourStore";

const PAD = 6;

const sameBox = (a: Box | null, b: Box | null) =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

/** Misst das Zielelement laufend (Layout ändert sich beim Laden, Scrollen, Live-Änderungen) und scrollt es einmal ins Bild. */
function useTargetBox(selector: string | undefined, stepId: string): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (!selector) { setBox(null); return; }
    let scrolled = false;
    const measure = () => {
      const el = document.querySelector(selector);
      if (!el) { setBox(null); return; }
      const r = el.getBoundingClientRect();
      if (!scrolled && (r.top < 80 || r.bottom > window.innerHeight - 80)) {
        const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        el.scrollIntoView({ block: "center", behavior: calm ? "auto" : "smooth" });
      }
      scrolled = true;
      const next = { top: r.top, left: r.left, width: r.width, height: r.height };
      setBox((prev) => (sameBox(prev, next) ? prev : next));
    };
    measure();
    const t = setInterval(measure, 150);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      clearInterval(t);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [selector, stepId]);
  return box;
}

const isEditable = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || el.tagName === "INPUT" || el.tagName === "TEXTAREA");

export function Guide() {
  const { docId, step: index } = useTour();
  const location = useLocation();
  const step = GUIDE_STEPS[index];
  const last = index === GUIDE_STEPS.length - 1;
  const onDoc = location.pathname === `/documents/${docId}`;
  const box = useTargetBox(onDoc ? step.target : undefined, step.id);
  const cardRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 360, height: 220 });
  const [done, setDone] = useState(false);

  // Mitmach-Erkennung: Ereignis im Zielbereich = geschafft
  useEffect(() => {
    setDone(false);
    const d = step.detect;
    if (!d || !onDoc) return;
    const on = (e: Event) => {
      if (!(e.target instanceof Element) || !e.target.closest(d.selector)) return;
      if (e.type === "keydown" && (e as KeyboardEvent).key.length !== 1) return;
      setDone(true);
    };
    d.events.forEach((ev) => document.addEventListener(ev, on, true));
    return () => d.events.forEach((ev) => document.removeEventListener(ev, on, true));
  }, [step, onDoc]);

  // Randleiste des ersten Blocks zeigen, auch ohne Maus darüber
  useEffect(() => {
    if (!step.showGutter || !onDoc) return;
    document.body.classList.add("tour-gutter");
    return () => document.body.classList.remove("tour-gutter");
  }, [step, onDoc]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isEditable(e.target)) closeTour();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useLayoutEffect(() => {
    const r = cardRef.current?.getBoundingClientRect();
    if (r && (Math.round(r.width) !== size.width || Math.round(r.height) !== size.height)) {
      setSize({ width: Math.round(r.width), height: Math.round(r.height) });
    }
  });

  if (!onDoc) {
    return (
      <div className="guide-paused" role="status">
        <span>Rundgang pausiert</span>
        <Link to={`/documents/${docId}`} className="btn btn-primary">Zurück zum Dokument</Link>
        <button className="ghost" onClick={closeTour}>Beenden</button>
      </div>
    );
  }

  const vp = { width: window.innerWidth, height: window.innerHeight };
  const pos = placeCard(box, size, vp, step.placement ?? "bottom");
  const centered = pos.side === "center";
  const next = () => (last ? closeTour() : setGuideStep(index + 1));

  return (
    <>
      {box && (
        <div
          className={`guide-spot ${step.dim === false ? "no-dim" : ""}`} aria-hidden="true"
          style={{ top: box.top - PAD, left: box.left - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2 }}
        />
      )}
      {centered && <div className="guide-veil" aria-hidden="true" />}
      <div
        ref={cardRef} key={step.id} className={`guide-card ${centered ? "centered" : ""}`} role="region" aria-label="Rundgang"
        style={{ top: pos.top, left: pos.left }}
      >
        {step.visual && <div className="tour-art guide-art" aria-hidden="true"><Visual kind={step.visual} /></div>}
        <p className="tour-count">Übung · {index + 1} von {GUIDE_STEPS.length}</p>
        <h2>{step.title}</h2>
        <p className="tour-text">{step.text}</p>
        {step.detect && (
          <p className={`guide-hint ${done ? "done" : ""}`} role="status">
            {done ? <Icon name="check" size={14} strokeWidth={2.6} /> : <span className="guide-pulse" />}
            {done ? step.detect.done : step.detect.hint}
          </p>
        )}
        <div className="guide-foot">
          {last ? <span /> : <button className="ghost" onClick={closeTour}>Beenden</button>}
          <div className="tour-actions">
            {index > 0 && !last && <button className="ghost" onClick={() => setGuideStep(index - 1)}>Zurück</button>}
            <button className="primary" onClick={next}>{last ? "Fertig" : "Weiter"}</button>
          </div>
        </div>
      </div>
    </>
  );
}
