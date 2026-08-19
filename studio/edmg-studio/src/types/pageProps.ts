import type { Page } from "../pageRouting";

export type StudioConfig = any;

export type NavigateFn = (page: Page) => void;

export type PageProps = {
  backendUrl: string;
  config: StudioConfig;
  onNavigate?: NavigateFn;
};
