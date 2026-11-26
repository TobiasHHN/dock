// Gemeinsamer Zustand eines Formulars für seine Felder und Zeilenlisten (Task 3.4).
import { createContext, useContext } from "react";
import type { Json } from "../sync/tableRules";
import type { FormErrors, Scope } from "./formModel";

export type FormContextValue = {
  formId: string;
  scope: Scope;
  values: Record<string, Json>;
  errors: FormErrors;
  setErrors: (fn: (e: FormErrors) => FormErrors) => void;
  /** Darf der Nutzer eintragen (L 4.3)? Sonst sind Felder schreibgeschützt. */
  fillable: boolean;
  /** Läuft gerade ein Absenden? Felder bleiben dann gesperrt. */
  busy: boolean;
};

export const FormContext = createContext<FormContextValue | null>(null);

export const useForm = (): FormContextValue | null => useContext(FormContext);
