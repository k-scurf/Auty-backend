import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { deleteProfile, fetchProfiles, profilePhotoUrl } from "../services/api";
import { EnrollmentFlow } from "../components/enrollment/EnrollmentFlow";
import { ScheduleEditor } from "../components/dashboard/ScheduleEditor";
import { useWebSocket } from "../hooks/useWebSocket";
import { EmployeeAvatar } from "../components/ui/EmployeeAvatar";
import { AttendanceBadge } from "../components/ui/AttendanceBadge";
import { Skeleton } from "../components/ui/Skeleton";
import type { Profile } from "../types";

function ProfileCard({
  profile,
  onDeleteRequest,
  onScheduleClick,
}: {
  profile: Profile;
  onDeleteRequest: () => void;
  onScheduleClick: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async () => {
    const profileKey = (profile.id ?? profile.name).trim();
    if (!profileKey) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteProfile(profileKey);
      setConfirming(false);
      onDeleteRequest();
    } catch {
      setDeleteError("Could not delete employee. Check the server connection and try again.");
    } finally {
      setDeleting(false);
    }
  };

  const enrolledDate = profile.enrolled_at
    ? new Date(profile.enrolled_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : null;

  return (
    <div className="card flex flex-col gap-3 p-4">
      <div className="flex items-start gap-3">
        <EmployeeAvatar name={profile.name} photo={profile.image ? profilePhotoUrl(profile.name) : undefined} size="xl" />
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-text-primary text-sm truncate">{profile.name}</div>
          {profile.status && (
            <AttendanceBadge
              variant="neutral"
              label={profile.status}
              className="mt-1"
            />
          )}
          {enrolledDate && (
            <div className="mt-1 text-[10px] font-mono text-text-muted">Enrolled {enrolledDate}</div>
          )}
        </div>
      </div>

      {!confirming ? (
        <div className="flex gap-2">
          <button
            onClick={onScheduleClick}
            className="btn-secondary flex-1 py-1.5 text-xs"
            title="Edit schedule"
          >
            <span className="inline-flex items-center justify-center gap-1.5">
              <svg width="13" height="13" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <rect x="3" y="4" width="14" height="13" rx="2" stroke="currentColor" strokeWidth="1.6" />
                <path d="M6 2.5v3M14 2.5v3M3 8h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
              Schedule
            </span>
          </button>
          <button
            onClick={() => setConfirming(true)}
            className="btn-ghost flex-1 py-1.5 text-xs text-text-muted hover:text-danger"
          >
            Delete data
          </button>
        </div>
      ) : (
        <div className="rounded-card border border-danger/30 bg-danger/5 p-3 space-y-2">
          <p className="text-xs text-danger">
            Permanently delete {profile.name} and all biometric data?
          </p>
          {deleteError && <p className="text-xs text-danger">{deleteError}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => { setConfirming(false); setDeleteError(null); }}
              className="btn-ghost text-xs flex-1 py-1"
              disabled={deleting}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleDelete}
              className="btn-danger text-xs flex-1 py-1"
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Confirm"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function ProfilesPage() {
  const { frame } = useWebSocket();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [showEnroll, setShowEnroll] = useState(false);
  const [scheduleFor, setScheduleFor] = useState<Profile | null>(null);

  const load = () => {
    setLoading(true);
    fetchProfiles()
      .then(setProfiles)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">Enrolled Employees</h2>
          <p className="text-xs text-text-muted mt-0.5">{profiles.length} employee{profiles.length !== 1 ? "s" : ""} on file</p>
        </div>
        <button onClick={() => setShowEnroll(true)} className="btn-primary">
          + Add Employee
        </button>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-32" />)}
        </div>
      ) : profiles.length === 0 ? (
        <div className="flex flex-col items-center gap-4 py-20 text-center">
          <div className="text-4xl">👥</div>
          <div>
            <div className="font-semibold text-text-primary">No employees enrolled</div>
            <div className="text-sm text-text-muted mt-1">Add employees to enable facial recognition clock-in</div>
          </div>
          <button onClick={() => setShowEnroll(true)} className="btn-primary mt-2">
            Enroll First Employee
          </button>
        </div>
      ) : (
        <>
          {scheduleFor && (
            <ScheduleEditor
              employeeId={scheduleFor.id ?? scheduleFor.name}
              employeeName={scheduleFor.name}
              onClose={() => setScheduleFor(null)}
            />
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {profiles.map((p) => (
              <ProfileCard
                key={p.id ?? p.name}
                profile={p}
                onDeleteRequest={load}
                onScheduleClick={() => setScheduleFor(p)}
              />
            ))}
          </div>
        </>
      )}

      <AnimatePresence>
        {showEnroll && (
          <EnrollmentFlow
            progress={frame?.enrollment_progress ?? null}
            onDone={() => { setShowEnroll(false); load(); }}
          />
        )}
      </AnimatePresence>
    </motion.div>
  );
}
