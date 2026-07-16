/**
 * Top-right hamburger menu holding the widget's secondary actions (Reports,
 * Add). A plain ☰ button that opens a small right-aligned popover; picking an
 * item runs its action and closes the menu. Dismisses on outside click.
 */

import { useEffect, useRef, useState } from "react";

import type { ThemeTokens } from "../lib/theme.ts";

export interface MenuItem {
  label: string;
  onClick: () => void;
  /** Rendered highlighted when its panel is currently open. */
  active?: boolean;
}

export function HamburgerMenu({
  tokens,
  items,
}: {
  tokens: ThemeTokens;
  items: MenuItem[];
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  if (items.length === 0) {
    return null;
  }

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <button
        type="button"
        aria-label="Menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 30,
          height: 28,
          padding: 0,
          background: "transparent",
          color: tokens.text,
          border: `1px solid ${tokens.border}`,
          borderRadius: 6,
          cursor: "pointer",
          fontSize: 15,
          lineHeight: 1,
        }}
      >
        ☰
      </button>

      {open && (
        <div
          role="menu"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            zIndex: 1000,
            minWidth: 160,
            background: tokens.bg,
            color: tokens.text,
            border: `1px solid ${tokens.border}`,
            borderRadius: 8,
            padding: 4,
            boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
              style={{
                textAlign: "left",
                padding: "6px 10px",
                fontSize: 13,
                background: item.active ? tokens.panel : "transparent",
                color: tokens.text,
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
