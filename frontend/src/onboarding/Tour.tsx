// Rundgang für neue Nutzer: erst eine ruhige Karte (Überblick), dann die Führung im Übungsdokument (Guide.tsx).
// Öffnet sich beim ersten Besuch und lässt sich über das Profilmenü jederzeit neu starten (`openTour`).
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { canEditDocument, useAuth } from "../api/client";
import { createBlankDocument } from "../documents/blockOps";
import { Icon } from "../ui/icons";
import { toast } from "../ui/toasts";
import { Guide } from "./Guide";
import { Visual } from "./TourVisuals";
import { TOUR_STEPS, clampStep, markTourSeen, tourSeen } from "./tourModel";
import { closeTour, openTour, startGuide, useTour } from "./tourStore";

export { openTour };

export function TourHost() {
  const user = useAuth((s) => s.user);
  const stage = useTour((s) => s.stage);
  const navigate = useNavigate();
  const [index, setIndex] = useState(0);
  const [creating, setCreating] = useState(false);
  const nextRef = useRef<HTMLButtonElement>(null);
  const last = TOUR_STEPS.length - 1;
  const mayCreate = canEditDocument(user);

  // Erster Besuch: automatisch öffnen
  useEffect(() => {
    if (user && !tourSeen(user.id)) openTour();
  }, [user]);

  const close = () => {
    if (user) markTourSeen(user.id);
    closeTour();
    setIndex(0);
  };
  const go = (i: number) => setIndex(clampStep(i));

  async function createPracticeDoc() {
    setCreating(true);
    try {
      const id = await createBlankDocument();
      if (user) markTourSeen(user.id);
      setIndex(0);
      startGuide(id);
      navigate(`/documents/${id}`);
    } catch (e) {
      toast(`Übungsdokument konnte nicht angelegt werden: ${(e as Error).message}`, "error");
    } finally {
      setCreating(false);
    }
  }

  const isLast = index === last;
  const next = () => (isLast ? (mayCreate ? void createPracticeDoc() : close()) : go(index + 1));
  const intro = stage === "intro";

  useEffect(() => {
    if (!intro) return;
    nextRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight" && !isLast) go(index + 1);
      else if (e.key === "ArrowLeft") go(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intro, index, user?.id]);

  if (stage === "guide") return <Guide />;
  if (!intro) return null;
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
            {index === 0 || isLast ? (
              <button className="ghost" onClick={close}>{isLast && mayCreate ? "Später" : "Überspringen"}</button>
            ) : (
              <button className="ghost" onClick={() => go(index - 1)}>Zurück</button>
            )}
            <button ref={nextRef} className="primary" onClick={next} disabled={creating}>
              {isLast ? (mayCreate ? (creating ? "Lege an …" : "Dokument anlegen") : "Fertig") : "Weiter"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
