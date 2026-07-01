import {
  AlertTriangle,
  Check,
  Cloud,
  Download,
  FileAudio,
  FileImage,
  FlaskConical,
  Gauge,
  ImagePlus,
  LoaderCircle,
  Mic2,
  MonitorCog,
  Play,
  RefreshCw,
  Save,
  ServerCog,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Upload,
  UserRound,
  Video,
  WandSparkles,
  Waves,
} from "lucide-react";

function DigitalHumanIcon({ size = 16, strokeWidth: _strokeWidth, className = "", ...props }) {
  return (
    <svg
      aria-hidden="true"
      className={`vf-icon ${className}`.trim()}
      focusable="false"
      height={size}
      viewBox="0 0 1024 1024"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path
        d="M683.712 331.392c0 111.232-92.928 201.6-208.256 203.328a30.72 30.72 0 0 1-6.592 0.704c-141.44 0-242.88 99.904-279.744 227.968-5.76 19.84 0 37.888 13.44 51.84 13.696 14.4 35.52 24.192 60.16 24.192h444.992c16.256 0 29.44 12.672 29.44 28.288a28.928 28.928 0 0 1-29.44 28.288H262.72c-40.448 0-78.272-16-103.616-42.496-25.728-26.88-38.4-64.768-26.752-105.152 31.68-109.952 108.16-208.32 219.904-249.28-55.488-36.672-91.84-98.112-91.84-167.68C260.416 219.072 355.136 128 472.064 128c116.864 0 211.648 91.072 211.648 203.392zM472.064 478.08c84.352 0 152.768-65.728 152.768-146.752 0-81.088-68.416-146.816-152.768-146.816S319.296 250.304 319.296 331.392c0 81.024 68.416 146.752 152.768 146.752z m293.952 56.64a28.864 28.864 0 0 0-29.44-28.288 28.864 28.864 0 0 0-29.44 28.288v205.44c0 15.552 13.184 28.224 29.44 28.224s29.44-12.608 29.44-28.288v-205.44zM636.032 657.92a28.864 28.864 0 0 0-29.44-28.288 28.864 28.864 0 0 0-29.44 28.288v82.176c0 15.616 13.12 28.288 29.44 28.288 16.256 0 29.44-12.672 29.44-28.288V657.92z m230.528-69.184c16.256 0 29.44 12.672 29.44 28.288v123.2a28.864 28.864 0 0 1-29.44 28.352 28.864 28.864 0 0 1-29.44-28.352V617.024c0-15.616 13.184-28.288 29.44-28.288z"
        fill="currentColor"
      />
    </svg>
  );
}

const ICONS = {
  alert: AlertTriangle,
  audio: FileAudio,
  check: Check,
  cloud: Cloud,
  digitalHuman: DigitalHumanIcon,
  download: Download,
  gauge: Gauge,
  image: FileImage,
  imageAdd: ImagePlus,
  lab: FlaskConical,
  loading: LoaderCircle,
  mic: Mic2,
  monitorCog: MonitorCog,
  play: Play,
  refresh: RefreshCw,
  save: Save,
  serverCog: ServerCog,
  settings: Settings,
  sliders: SlidersHorizontal,
  sparkles: Sparkles,
  upload: Upload,
  user: UserRound,
  video: Video,
  wand: WandSparkles,
  waves: Waves,
};

export default function Icon({ name, size = 16, strokeWidth = 1.8, className = "", ...props }) {
  const Component = ICONS[name] ?? Sparkles;

  return (
    <Component
      aria-hidden="true"
      className={`vf-icon ${className}`.trim()}
      focusable="false"
      size={size}
      strokeWidth={strokeWidth}
      {...props}
    />
  );
}
