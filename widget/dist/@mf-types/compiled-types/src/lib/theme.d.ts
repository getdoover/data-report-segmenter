/**
 * Resolve a small, swappable set of style tokens from the host's emotion/MUI
 * theme (`ui_element_props.theme`), falling back to prefers-color-scheme.
 *
 * Kept pure so the presentation stays theme-aware without hard-coding a single
 * palette. The token set is intentionally tiny — this UX will be iterated on.
 */
export interface ThemeTokens {
    dark: boolean;
    bg: string;
    panel: string;
    border: string;
    text: string;
    subtext: string;
    accent: string;
    accentText: string;
    danger: string;
    disabledBg: string;
}
/**
 * @param theme       host `ui_element_props.theme` (emotion theme, may be null)
 * @param prefersDark  result of prefers-color-scheme media query
 */
export declare function resolveTheme(theme: unknown, prefersDark: boolean): ThemeTokens;
