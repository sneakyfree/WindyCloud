import { ArrowRight, Check, Cloud, Cpu, HardDrive, Server } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { markCloudTourSeen } from "../tourState";

type Step = {
  icon: typeof HardDrive;
  title: string;
  blurb: string;
  color: string;
};

const STEPS: Step[] = [
  {
    icon: HardDrive,
    title: "Storage",
    blurb:
      "Every Windy app backs up here automatically — 5 GB free, no setup.",
    color: "var(--accent)",
  },
  {
    icon: Cpu,
    title: "Compute",
    blurb:
      "Offload heavy work (like voice-to-text) to GPUs you pay for only when you use them.",
    color: "var(--yellow)",
  },
  {
    icon: Server,
    title: "Servers",
    blurb:
      "Spin up cloud servers tied to your Windy identity — one bill, one login.",
    color: "var(--green)",
  },
];

export default function CloudTour() {
  const navigate = useNavigate();

  const finish = () => {
    markCloudTourSeen();
    navigate("/", { replace: true });
  };

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-2">
        <Cloud className="w-7 h-7 text-[var(--accent)]" />
        <h1 className="text-2xl font-semibold">Welcome to Windy Cloud</h1>
      </div>
      <p className="text-sm text-[var(--text-muted)] mb-6">
        Three things you get out of the box — nothing to configure.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {STEPS.map((step) => (
          <div
            key={step.title}
            className="bg-[var(--bg-card)] rounded-xl p-5 border border-[var(--border)]"
          >
            <div className="flex items-center gap-2 mb-3">
              <step.icon className="w-5 h-5" style={{ color: step.color }} />
              <span className="font-medium">{step.title}</span>
              <Check className="w-4 h-4 text-[var(--green)] ml-auto" />
            </div>
            <p className="text-sm text-[var(--text-muted)] leading-relaxed">
              {step.blurb}
            </p>
          </div>
        ))}
      </div>

      <button
        onClick={finish}
        className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[var(--accent)] text-white text-sm hover:bg-[var(--accent-hover)] transition-colors cursor-pointer"
      >
        Get started <ArrowRight className="w-4 h-4" />
      </button>
    </div>
  );
}
