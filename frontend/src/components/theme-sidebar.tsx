"use client";

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  pointerWithin,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  type UniqueIdentifier,
  useSensor,
  useSensors
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Minus, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { themeDisplayName } from "@/lib/i18n";
import { GLASS_MUTED, glassNavClass } from "@/lib/nav-glass";
import type { Locale, ThemeRow } from "@/lib/types";

type ThemeSidebarProps = {
  locale: Locale;
  themes: ThemeRow[];
  selectedThemeId?: number;
  collection: string;
  onSelectAll: () => void;
  onSelectTheme: (themeId: number) => void;
  onCreateTheme: (name: string, description: string) => Promise<void>;
  onDeleteTheme: (themeId: number) => Promise<{ remapped: number }>;
  onReorderThemes: (themeIds: number[]) => Promise<void>;
  onUpdateThemeDescription: (themeId: number, description: string) => Promise<void>;
  onAbsorbFromTheme?: (targetThemeId: number, sourceThemeId: number) => Promise<void>;
  labels: {
    themes: string;
    allThemes: string;
    addTheme: string;
    themeName: string;
    themeDesc: string;
    editThemeDesc: string;
    themeDescSave: string;
    themeDescCancel: string;
    themeAbsorbFromResearch: string;
    deleteTheme: string;
    confirmDeleteTheme: string;
    themeDeleted: string;
    cannotDeleteBuiltin: string;
    deletingTheme: string;
    done: string;
  };
};

function themeIdKey(id: UniqueIdentifier | number): string {
  return String(id);
}

function findThemeIndex(items: ThemeRow[], id: UniqueIdentifier): number {
  const key = themeIdKey(id);
  return items.findIndex((row) => themeIdKey(row.id) === key);
}

function sameOrder(a: ThemeRow[], b: ThemeRow[]): boolean {
  if (a.length !== b.length) {
    return false;
  }
  return a.every((row, index) => row.id === b[index]?.id);
}

const themeListCollision: CollisionDetection = (args) => {
  const pointerHits = pointerWithin(args);
  if (pointerHits.length > 0) {
    return pointerHits;
  }
  return closestCorners(args);
};

function themeDescription(theme: ThemeRow, locale: Locale): string {
  if (locale === "en") {
    return theme.description_en?.trim() || theme.description_zh?.trim() || "";
  }
  return theme.description_zh?.trim() || theme.description_en?.trim() || "";
}

type ThemeEditCardProps = {
  locale: Locale;
  theme: ThemeRow;
  overlay?: boolean;
  dragProps?: React.HTMLAttributes<HTMLDivElement>;
};

function ThemeEditCard(props: ThemeEditCardProps): JSX.Element {
  const { locale, theme, overlay = false, dragProps } = props;

  return (
    <div
      className={`theme-card-3d theme-sort-card rounded-md border border-border bg-gradient-to-br from-surface via-surface to-panel px-2 py-1.5 ${
        overlay ? "theme-sort-overlay shadow-lg" : ""
      }`}
      {...(overlay ? {} : dragProps)}
    >
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="min-w-0 flex-1 truncate font-medium text-foreground">
          {themeDisplayName(theme, locale)}
        </span>
        <span className="shrink-0 text-xs text-muted">{theme.item_count}</span>
      </div>
    </div>
  );
}

type SortableThemeItemProps = {
  locale: Locale;
  theme: ThemeRow;
  sorting: boolean;
  disabled: boolean;
  deleting: boolean;
  deleteLabel: string;
  deletingLabel: string;
  onDelete: (theme: ThemeRow, event: React.MouseEvent) => void;
  onEditDescription: (theme: ThemeRow) => void;
};

function SortableThemeItem(props: SortableThemeItemProps): JSX.Element {
  const {
    locale,
    theme,
    sorting,
    disabled,
    deleting,
    deleteLabel,
    deletingLabel,
    onDelete,
    onEditDescription
  } = props;

  const sortableId = themeIdKey(theme.id);
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging
  } = useSortable({ id: sortableId, disabled });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition: transition ?? undefined,
    zIndex: isDragging ? 0 : 1
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`theme-sort-row relative pl-4 ${isDragging ? "theme-sort-row-placeholder" : ""}`}
    >
      <button
        type="button"
        disabled={Boolean(theme.is_builtin) || disabled || deleting}
        onClick={(e) => onDelete(theme, e)}
        onPointerDown={(e) => e.stopPropagation()}
        title={deleting ? deletingLabel : deleteLabel}
        aria-label={deleting ? deletingLabel : deleteLabel}
        aria-busy={deleting}
        className={`absolute left-0 top-1/2 z-10 flex h-3.5 w-3.5 -translate-y-1/2 items-center justify-center rounded-full border bg-surface shadow-sm transition-colors disabled:cursor-not-allowed disabled:border-border disabled:text-muted disabled:hover:bg-surface ${
          deleting
            ? "border-border text-muted"
            : "border-red-500 text-red-500 hover:bg-red-500/10"
        }`}
      >
        <Minus className="h-2 w-2" strokeWidth={4.5} absoluteStrokeWidth />
      </button>
      <div
        className={`theme-card-jitter min-w-0 ${sorting ? "theme-edit-sorting" : ""}`}
        onDoubleClick={() => onEditDescription(theme)}
      >
        <ThemeEditCard
          locale={locale}
          theme={theme}
          dragProps={{ ...attributes, ...listeners }}
        />
      </div>
    </div>
  );
}

export function ThemeSidebar(props: ThemeSidebarProps): JSX.Element {
  const {
    locale,
    themes,
    selectedThemeId,
    collection,
    onSelectAll,
    onSelectTheme,
    onCreateTheme,
    onDeleteTheme,
    onReorderThemes,
    onUpdateThemeDescription,
    onAbsorbFromTheme,
    labels
  } = props;

  const [editMode, setEditMode] = useState(false);
  const [orderedThemes, setOrderedThemes] = useState<ThemeRow[]>(themes);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [adding, setAdding] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [activeTheme, setActiveTheme] = useState<ThemeRow | null>(null);
  const [savingOrder, setSavingOrder] = useState(false);
  const [descDialog, setDescDialog] = useState<ThemeRow | null>(null);
  const [descText, setDescText] = useState("");
  const [savingDesc, setSavingDesc] = useState(false);
  const orderedRef = useRef(orderedThemes);
  const dragStartThemesRef = useRef<ThemeRow[] | null>(null);
  const lastOverIdRef = useRef<UniqueIdentifier | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  useEffect(() => {
    const next = [...themes];
    orderedRef.current = next;
    if (!editMode) {
      setOrderedThemes(next);
      return;
    }
    if (activeTheme === null && !savingOrder) {
      setOrderedThemes(next);
    }
  }, [themes, editMode, activeTheme, savingOrder]);

  useEffect(() => {
    if (!descDialog) {
      return;
    }
    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape" && !savingDesc) {
        setDescDialog(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [descDialog, savingDesc]);

  function openDescDialog(theme: ThemeRow): void {
    setDescDialog(theme);
    setDescText(themeDescription(theme, locale));
  }

  function researchThemeId(): number | undefined {
    return themes.find((row) => row.slug === "research")?.id;
  }

  function canAbsorbFromResearch(theme: ThemeRow): boolean {
    return theme.slug === "科技" && researchThemeId() !== undefined && onAbsorbFromTheme !== undefined;
  }

  async function triggerAbsorbFromResearch(theme: ThemeRow): Promise<void> {
    const sourceId = researchThemeId();
    if (!sourceId || !onAbsorbFromTheme) {
      return;
    }
    await onAbsorbFromTheme(theme.id, sourceId);
  }

  async function handleSaveDescription(): Promise<void> {
    if (!descDialog || savingDesc) {
      return;
    }
    const saved = descDialog;
    setSavingDesc(true);
    try {
      await onUpdateThemeDescription(saved.id, descText.trim());
      setDescDialog(null);
      if (canAbsorbFromResearch(saved)) {
        await triggerAbsorbFromResearch(saved);
      }
    } finally {
      setSavingDesc(false);
    }
  }

  async function handleDelete(theme: ThemeRow, event: React.MouseEvent): Promise<void> {
    event.stopPropagation();
    event.preventDefault();
    if (theme.is_builtin || deletingId !== null || savingOrder) {
      if (theme.is_builtin) {
        window.alert(labels.cannotDeleteBuiltin);
      }
      return;
    }
    const name = themeDisplayName(theme, locale);
    const count = String(theme.item_count ?? 0);
    if (
      !window.confirm(
        labels.confirmDeleteTheme.replace("{name}", name).replace("{n}", count)
      )
    ) {
      return;
    }
    setDeletingId(theme.id);
    try {
      await onDeleteTheme(theme.id);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleAdd(): Promise<void> {
    const name = newName.trim();
    if (!name) {
      return;
    }
    await onCreateTheme(name, newDescription.trim());
    setNewName("");
    setNewDescription("");
    setAdding(false);
  }

  function applyMove(items: ThemeRow[], activeId: UniqueIdentifier, overId: UniqueIdentifier): ThemeRow[] {
    const oldIndex = findThemeIndex(items, activeId);
    const newIndex = findThemeIndex(items, overId);
    if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) {
      return items;
    }
    return arrayMove(items, oldIndex, newIndex);
  }

  async function persistOrder(next: ThemeRow[], previous: ThemeRow[]): Promise<void> {
    setOrderedThemes(next);
    orderedRef.current = next;
    setSavingOrder(true);
    try {
      await onReorderThemes(next.map((row) => row.id));
    } catch (error) {
      setOrderedThemes(previous);
      orderedRef.current = previous;
      throw error;
    } finally {
      setSavingOrder(false);
    }
  }

  function handleDragStart(event: DragStartEvent): void {
    dragStartThemesRef.current = [...orderedRef.current];
    lastOverIdRef.current = null;
    const theme = orderedRef.current.find(
      (row) => themeIdKey(row.id) === themeIdKey(event.active.id)
    );
    setActiveTheme(theme ?? null);
  }

  function handleDragOver(event: DragOverEvent): void {
    const { active, over } = event;
    if (!over || themeIdKey(active.id) === themeIdKey(over.id)) {
      return;
    }
    lastOverIdRef.current = over.id;
    setOrderedThemes((items) => {
      const next = applyMove(items, active.id, over.id);
      if (next === items) {
        return items;
      }
      orderedRef.current = next;
      return next;
    });
  }

  function handleDragEnd(event: DragEndEvent): void {
    setActiveTheme(null);
    const previous = dragStartThemesRef.current;
    dragStartThemesRef.current = null;
    if (savingOrder || !previous) {
      lastOverIdRef.current = null;
      return;
    }

    const { active } = event;
    const overId = event.over?.id ?? lastOverIdRef.current;
    lastOverIdRef.current = null;

    let current = orderedRef.current;
    if (overId && themeIdKey(active.id) !== themeIdKey(overId)) {
      const moved = applyMove(previous, active.id, overId);
      if (!sameOrder(moved, current)) {
        current = moved;
        setOrderedThemes(current);
        orderedRef.current = current;
      }
    }

    if (!sameOrder(current, previous)) {
      void persistOrder(current, previous).catch(() => {
        /* parent shows error in toolbar */
      });
    }
  }

  function handleDragCancel(): void {
    setActiveTheme(null);
    lastOverIdRef.current = null;
    const previous = dragStartThemesRef.current;
    dragStartThemesRef.current = null;
    if (previous) {
      setOrderedThemes(previous);
      orderedRef.current = previous;
    }
  }

  const sortingActive = activeTheme !== null || savingOrder;
  const sortableIds = orderedThemes.map((row) => themeIdKey(row.id));
  const dragDisabled = savingOrder || deletingId !== null;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-xs font-medium uppercase tracking-wider text-muted">
          {labels.themes}
        </h2>
        <button
          type="button"
          onClick={() => {
            setEditMode((v) => !v);
            setAdding(false);
            setNewName("");
            setActiveTheme(null);
            dragStartThemesRef.current = null;
            lastOverIdRef.current = null;
          }}
          title={editMode ? labels.done : labels.addTheme}
          aria-label={editMode ? labels.done : labels.addTheme}
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors ${
            editMode
              ? "border-foreground bg-inverse text-inverse-foreground"
              : "border-border bg-surface text-muted hover:border-muted hover:text-foreground"
          }`}
        >
          {editMode ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
        </button>
      </div>

      {editMode ? (
        <div>
          <DndContext
            sensors={sensors}
            collisionDetection={themeListCollision}
            autoScroll={{ enabled: true, threshold: { x: 0, y: 0.12 } }}
            onDragStart={handleDragStart}
            onDragOver={handleDragOver}
            onDragEnd={handleDragEnd}
            onDragCancel={handleDragCancel}
          >
            <div
              className={`theme-edit-stack theme-edit-list flex flex-col gap-2 py-0.5 ${
                sortingActive ? "theme-edit-sorting" : ""
              }`}
            >
              <SortableContext items={sortableIds} strategy={verticalListSortingStrategy}>
                {orderedThemes.map((theme) => (
                  <SortableThemeItem
                    key={theme.id}
                    locale={locale}
                    theme={theme}
                    sorting={sortingActive}
                    disabled={dragDisabled}
                    deleting={deletingId === theme.id}
                    deleteLabel={labels.deleteTheme}
                    deletingLabel={labels.deletingTheme}
                    onDelete={(t, e) => void handleDelete(t, e)}
                    onEditDescription={openDescDialog}
                  />
                ))}
              </SortableContext>
              {adding ? (
                <div className="ml-4 rounded-md border border-dashed border-border bg-panel p-2">
                  <input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder={labels.themeName}
                    className="mb-2 w-full rounded border border-border bg-surface px-2 py-1 text-sm text-foreground"
                  />
                  <textarea
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder={labels.themeDesc}
                    rows={2}
                    className="mb-2 w-full resize-none rounded border border-border bg-surface px-2 py-1 text-sm text-foreground"
                  />
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => void handleAdd()}
                      className="flex-1 rounded border border-foreground bg-inverse py-1 text-xs text-inverse-foreground"
                    >
                      {labels.addTheme}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setAdding(false);
                        setNewName("");
                        setNewDescription("");
                      }}
                      className="rounded border border-border px-2 py-1 text-xs hover:bg-soft"
                    >
                      {labels.done}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setAdding(true)}
                  disabled={savingOrder}
                  className="ml-4 w-[calc(100%-1rem)] rounded-md border border-dashed border-border py-1.5 text-xs text-muted hover:border-muted hover:text-foreground disabled:opacity-50"
                >
                  + {labels.addTheme}
                </button>
              )}
            </div>
            <DragOverlay
              dropAnimation={{
                duration: 280,
                easing: "cubic-bezier(0.25, 1, 0.5, 1)"
              }}
            >
              {activeTheme ? (
                <div className="theme-sort-row relative pl-4">
                  <div className="theme-card-jitter min-w-0 theme-edit-sorting">
                    <ThemeEditCard locale={locale} theme={activeTheme} overlay />
                  </div>
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
        </div>
      ) : (
        <div className="space-y-0.5">
          <button
            type="button"
            onClick={onSelectAll}
            className={`w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
              selectedThemeId === undefined && collection === "feed"
            )}`}
          >
            {labels.allThemes}
          </button>
          {themes.map((theme) => (
            <button
              key={theme.id}
              type="button"
              onClick={() => onSelectTheme(theme.id)}
              onDoubleClick={() => openDescDialog(theme)}
              className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors ${glassNavClass(
                selectedThemeId === theme.id && collection === "feed"
              )}`}
            >
              <span className="truncate">{themeDisplayName(theme, locale)}</span>
              <span
                className={`shrink-0 text-xs ${
                  selectedThemeId === theme.id && collection === "feed"
                    ? GLASS_MUTED
                    : "text-muted"
                }`}
              >
                {theme.item_count}
              </span>
            </button>
          ))}
        </div>
      )}

      {descDialog ? (
        <div
          className="fixed inset-0 z-[110] flex items-center justify-center bg-black/40 p-4"
          onClick={() => {
            if (!savingDesc) {
              setDescDialog(null);
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-sm rounded-lg border border-border bg-surface p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-1 text-sm font-medium text-foreground">
              {labels.editThemeDesc}
            </h3>
            <p className="mb-3 truncate text-xs text-muted">
              {themeDisplayName(descDialog, locale)}
            </p>
            <textarea
              value={descText}
              onChange={(e) => setDescText(e.target.value)}
              placeholder={labels.themeDesc}
              rows={4}
              autoFocus
              disabled={savingDesc}
              className="mb-3 w-full resize-none rounded border border-border bg-panel px-2 py-1.5 text-sm text-foreground disabled:opacity-60"
            />
            <div className="flex flex-wrap justify-end gap-2">
              {descDialog && canAbsorbFromResearch(descDialog) ? (
                <button
                  type="button"
                  disabled={savingDesc}
                  onClick={() => void triggerAbsorbFromResearch(descDialog)}
                  className="mr-auto rounded border border-border px-3 py-1.5 text-xs hover:bg-soft disabled:opacity-50"
                >
                  {labels.themeAbsorbFromResearch}
                </button>
              ) : null}
              <button
                type="button"
                disabled={savingDesc}
                onClick={() => setDescDialog(null)}
                className="rounded border border-border px-3 py-1.5 text-xs hover:bg-soft disabled:opacity-50"
              >
                {labels.themeDescCancel}
              </button>
              <button
                type="button"
                disabled={savingDesc}
                onClick={() => void handleSaveDescription()}
                className="rounded border border-foreground bg-inverse px-3 py-1.5 text-xs text-inverse-foreground disabled:opacity-50"
              >
                {labels.themeDescSave}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
