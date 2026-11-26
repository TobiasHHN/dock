// Rundgang für neue Nutzer: eine ruhige Karte mit fünf Schritten, öffnet sich beim ersten Besuch
// und lässt sich über das Fragezeichen in der Kopfzeile jederzeit wieder starten.
import { useEffect, useRef, useState } from "react";
import { create } from "zustand";
import { useAuth } from "../api/client";
import { Icon } from "../ui/icons";
import { TOUR_STEPS, type TourVisual, clampStep, markTourSeen, tourSeen } from "./tourModel";

const useTour = create<{ open: boolean }>(() => ({ open: false }));

export const openTour = () => useTour.setState({ open: true });

/** Fragezeichen in der Kopfzeile. */
export function TourButton() {
  return (
    <button className="icon-button" onClick={openTour} aria-label="Rundgang starten" title="Rundgang">
      <Icon name="help" size={18} strokeWidth={1.8} />
    </button>
  );
}

function Visual({ kind }: { kind: TourVisual }) {
  switch (kind) {
    case "welcome":
      return (
        <div className="tour-vis tour-vis-welcome">
          <span><Icon name="file" size={22} strokeWidth={1.6} /></span>
          <span><Icon name="table" size={22} strokeWidth={1.6} /></span>
          <span><Icon name="flow" size={22} strokeWidth={1.6} /></span>
        </div>
      );
    case "documents":
      return (
        <div className="tour-vis tour-mock-list">
          <div className="tour-mock-row"><Icon name="chevronRight" size={14} /><Icon name="flow" size={16} /><b>Bestellfreigabe</b><em>3 Dokumente</em></div>
          <div className="tour-mock-row child"><Icon name="file" size={16} /><span>Bestellung prüfen</span></div>
          <div className="tour-mock-row child"><Icon name="file" size={16} /><span>Freigabe Chef</span></div>
        </div>
      );
    case "tasks":
      return (
        <div className="tour-vis tour-mock-col">
          <div className="tour-mock-nav"><span>Zu erledigen</span><i className="badge">2</i></div>
          <div className="tour-mock-row"><Icon name="clock" size={16} /><span>Schritt „Prüfen“</span><em className="tour-pill">Übernehmen</em></div>
        </div>
      );
    case "requests":
      return (
        <div className="tour-vis tour-mock-col">
          <div className="tour-mock-steps"><i className="done" /><u className="done" /><i className="done" /><u /><i /></div>
          <div className="tour-mock-row"><span>Bestellung 4711</span><em className="tour-pill">In Prüfung · Anna</em></div>
        </div>
      );
    case "search":
      return (
        <div className="tour-vis tour-mock-search">
          <div className="tour-mock-field"><Icon name="search" size={16} /><span>Bestellung</span></div>
          <span className="tour-mock-bell"><Icon name="bell" size={18} /><i /></span>
        </div>
      );
  }
}

export function TourHost() {
  const user = useAuth((s) => s.user);
  const open = useTour((s) => s.open);
  const [index, setIndex] = useState(0);
  const nextRef = useRef<HTMLButtonElement>(null);
  const last = TOUR_STEPS.length - 1;

  // Erster Besuch: automatisch öffnen
  useEffect(() => {
    if (user && !tourSeen(user.id)) useTour.setState({ open: true });
  }, [user]);

  const close = () => {
    if (user) markTourSeen(user.id);
    useTour.setState({ open: false });
    setIndex(0);
  };
  const go = (i: number) => setIndex(clampStep(i));
  const next = () => (index >= last ? close() : go(index + 1));

  useEffect(() => {
    if (!open) return;
    nextRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") go(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, index, user?.id]);

  if (!open) return null;
  const step = TOUR_STEPS[index];
  return (
    <div className="tour-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="tour" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-text">
        <button className="icon-button tour-close" onClick={close} aria-label="Rundgang schließen">
          <Icon name="close" size={16} />
        </button>
        <div key={step.id} className="tour-step">
          <div className="tour-art" aria-hidden="true"><Visual kind={step.visual} /></div>
          <p className="tour-count">{index + 1} von {TOUR_STEPS.length}</p>
          <h2 id="tour-title">{step.title}</h2>
          <p id="tour-text" className="tour-text">{step.text}</p>
        </div>
        <div className="tour-foot">
          <div className="tour-dots" role="group" aria-label="Schritt wählen">
            {TOUR_STEPS.map((s, i) => (
              <button
                key={s.id} type="button" className={i === index ? "active" : ""}
                aria-label={`Schritt ${i + 1}: ${s.title}`} aria-current={i === index ? "step" : undefined}
                onClick={() => go(i)}
              />
            ))}
          </div>
          <div className="tour-actions">
            {index === 0 ? (
              <button className="ghost" onClick={close}>Überspringen</button>
            ) : (
              <button className="ghost" onClick={() => go(index - 1)}>Zurück</button>
            )}
            <button ref={nextRef} className="primary" onClick={next}>
              {index === last ? "Los geht’s" : "Weiter"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
