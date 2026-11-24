import {
  BookOpen,
  Boxes,
  ClipboardCheck,
  LayoutDashboard,
  Library,
  ScanLine,
  ShieldAlert,
} from "lucide-react";

export const workspaceConfig = {
  name: "Posify",
  tagline: "Industrial vision workspace",
  defaultPage: "captures",
  capability: "Nameplate detection + OCR",
  navigation: [
    {
      label: "Workspace",
      items: [
        { id: "captures", label: "Identify equipment", icon: ScanLine },
        { id: "overview", label: "Overview", icon: LayoutDashboard },
        { id: "assets", label: "Factory assets", icon: Boxes },
        { id: "inspections", label: "Inspections", icon: ClipboardCheck },
        { id: "corrections", label: "Corrections", icon: ShieldAlert },
      ],
    },
    {
      label: "Reference",
      items: [
        { id: "catalogue", label: "Global catalogue", icon: Library },
        { id: "knowledge", label: "Knowledge", icon: BookOpen },
      ],
    },
  ],
} as const;
