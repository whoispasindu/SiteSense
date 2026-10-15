import { useNavigate } from "react-router";

import { fetchMe } from "../../api/auth";
import { useAuth } from "../../auth/context";
import { Button } from "../../components/ui/Button";
import { MfaSetupFlow } from "../../features/auth/TwoStep";
import { GateLayout, GatePass } from "./GateLayout";

/** Roles that need two-step sign-in (Company Admin, PM, QS, procurement) set it up here before anything else. */
export function TwoStepSetupPage() {
  const { user, setUser, signOut } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;

  async function finish() {
    setUser(await fetchMe());
    void navigate("/", { replace: true });
  }

  return (
    <GateLayout>
      <GatePass title="Set up two-step sign-in">
        <p className="mt-2 text-ink-soft">
          As a {user.role_label.toLowerCase()} you see costs or run the company, so SiteSense asks for a code from your
          phone as well as your password.
        </p>
        <div className="mt-6">
          <MfaSetupFlow onFinished={() => void finish()} />
        </div>
        <div className="mt-6 border-t border-rule pt-4 text-sm">
          <Button onClick={() => void signOut()} className="w-full">
            Sign out and do this later
          </Button>
        </div>
      </GatePass>
    </GateLayout>
  );
}
