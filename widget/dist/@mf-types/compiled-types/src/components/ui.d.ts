/**
 * Tiny, swappable themed primitives (inline-styled from ThemeTokens). Kept
 * deliberately small — the segmenter UX is expected to be iterated on, so
 * presentation stays isolated from logic. No external UI library.
 */
import type { CSSProperties, ReactNode } from "react";
import type { ThemeTokens } from "../lib/theme.ts";
export declare function Card({ tokens, children, style, }: {
    tokens: ThemeTokens;
    children: ReactNode;
    style?: CSSProperties;
}): import("react").JSX.Element;
export declare function Select({ tokens, value, options, onChange, disabled, ariaLabel, }: {
    tokens: ThemeTokens;
    value: string;
    options: string[];
    onChange: (value: string) => void;
    disabled?: boolean;
    ariaLabel?: string;
}): import("react").JSX.Element;
export declare function Button({ tokens, children, onClick, disabled, variant, style, }: {
    tokens: ThemeTokens;
    children: ReactNode;
    onClick?: () => void;
    disabled?: boolean;
    variant?: "primary" | "ghost";
    style?: CSSProperties;
}): import("react").JSX.Element;
export declare function Field({ tokens, label, children, }: {
    tokens: ThemeTokens;
    label: string;
    children: ReactNode;
}): import("react").JSX.Element;
export declare function DateTimeInput({ tokens, value, onChange, }: {
    tokens: ThemeTokens;
    value: string;
    onChange: (value: string) => void;
}): import("react").JSX.Element;
