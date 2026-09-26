"use client";

import type { ReactNode } from "react";

import { Drawer, DrawerContent, DrawerDescription, DrawerTitle } from "@/components/ui/drawer";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/lib/use-media-query";

type DetailPanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The dialog's accessible name and visible heading. */
  title: string;
  /** Screen-reader description of what the panel is for. */
  description: string;
  children: ReactNode;
  footer?: ReactNode;
};

/**
 * Item details (goals now, tasks in F1.5): a sheet from the right from 768px, a bottom drawer with
 * swipe-to-dismiss below (design-system.md §6.2). The list stays in place behind it, and Radix
 * returns focus to whatever opened it.
 */
export function DetailPanel({ open, onOpenChange, title, description, children, footer }: DetailPanelProps) {
  const desktop = useMediaQuery("(min-width: 768px)");

  const body = (
    <>
      <div className="flex-1 overflow-y-auto px-5 pb-5">{children}</div>
      {footer && <div className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">{footer}</div>}
    </>
  );

  if (desktop) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent>
          <div className="px-5 pt-5 pr-14 pb-4">
            <SheetTitle className="line-clamp-2">{title}</SheetTitle>
            <SheetDescription className="sr-only">{description}</SheetDescription>
          </div>
          {body}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent>
        <div className="px-5 pt-3 pb-4">
          <DrawerTitle className="line-clamp-2">{title}</DrawerTitle>
          <DrawerDescription className="sr-only">{description}</DrawerDescription>
        </div>
        {body}
      </DrawerContent>
    </Drawer>
  );
}
