// Zustand des Rundgangs: erst die Karte („intro“), danach die Führung im Übungsdokument („guide“).
import { create } from "zustand";

export type TourStage = "closed" | "intro" | "guide";

type TourState = { stage: TourStage; docId: string | null; step: number };

export const useTour = create<TourState>(() => ({ stage: "closed", docId: null, step: 0 }));

export const openTour = () => useTour.setState({ stage: "intro", docId: null, step: 0 });
export const startGuide = (docId: string) => useTour.setState({ stage: "guide", docId, step: 0 });
export const setGuideStep = (step: number) => useTour.setState({ step });
export const closeTour = () => useTour.setState({ stage: "closed", docId: null, step: 0 });
