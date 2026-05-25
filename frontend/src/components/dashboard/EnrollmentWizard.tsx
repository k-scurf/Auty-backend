import { EnrollmentFlow } from "../enrollment/EnrollmentFlow";
import type { EnrollmentProgress } from "../../types";

interface Props {
  progress: EnrollmentProgress | null | undefined;
  legacyImageB64?: string;
  onDone: () => void;
}

export function EnrollmentWizard({ progress, legacyImageB64, onDone }: Props) {
  return (
    <EnrollmentFlow
      progress={progress}
      previewB64={legacyImageB64}
      onDone={onDone}
    />
  );
}
