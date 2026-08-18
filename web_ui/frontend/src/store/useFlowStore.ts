import { create } from 'zustand';

/** 统一流程大页面（#178）中四个 section 的 id，与导航项一一对应 */
export type FlowSectionId = 'drive' | 'tub-manager' | 'trainer' | 'pilot';

type FlowState = {
  /** 当前滚动位置对应的 section，用于导航高亮（scroll spy） */
  activeSection: FlowSectionId;
  setActiveSection: (id: FlowSectionId) => void;
};

export const useFlowStore = create<FlowState>((set) => ({
  activeSection: 'drive',
  setActiveSection: (id) => set({ activeSection: id }),
}));
