import { useCallback } from "react";
import { useSearchParams } from "react-router";

import type { JobStatus, JobType, JobsFilter } from "../../api/jobs";
import { isJobStatus, isJobType } from "./jobFormat";

const PROJECT_PARAM = "project";
const STATUS_PARAM = "status";
const TYPE_PARAM = "type";
const PAGE_PARAM = "page";

/** The value meaning "the jobs of the labs", which belong to no project. */
const LAB_PROJECT = "lab";

/**
 * A positive whole number, or null when `value` is missing or is something else. A stray value
 * in the address must never reach the server as an id or a page.
 */
function positiveIntegerFrom(value: string | null): number | null {
  if (value === null || !/^[1-9][0-9]{0,15}$/.test(value)) {
    return null;
  }
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : null;
}

function projectFrom(value: string | null): JobsFilter["project"] {
  return value === LAB_PROJECT ? LAB_PROJECT : positiveIntegerFrom(value);
}

/** The known values of a repeated parameter, each once, in the order they have in the address. */
function knownValues<T extends string>(
  values: string[],
  isKnown: (value: string) => value is T,
): T[] {
  return [...new Set(values)].filter(isKnown);
}

export type ActivityFilters = {
  filter: JobsFilter;
  /** The page of the list, from 1. */
  page: number;
  /** True when any filter is on. */
  hasFilters: boolean;
  setProject: (project: JobsFilter["project"]) => void;
  setStatuses: (statuses: JobStatus[]) => void;
  setTypes: (types: JobType[]) => void;
  setPage: (page: number) => void;
  /** Turns every filter off, and goes back to the first page. */
  clear: () => void;
};

/**
 * The Activity page's filters and page, kept in the address
 * (`/activity?project=3&status=failed&status=cancelled&type=generate_shot&page=2`), so a
 * reload, the back button or a link keeps them. Values the address has that are not valid are
 * ignored. Changing a filter goes back to the first page. A change replaces the entry in the
 * browser's history instead of adding one, so the back button leaves the page.
 */
export function useActivityFilters(): ActivityFilters {
  const [params, setParams] = useSearchParams();

  const filter: JobsFilter = {
    project: projectFrom(params.get(PROJECT_PARAM)),
    statuses: knownValues(params.getAll(STATUS_PARAM), isJobStatus),
    types: knownValues(params.getAll(TYPE_PARAM), isJobType),
  };
  const page = positiveIntegerFrom(params.get(PAGE_PARAM)) ?? 1;
  const hasFilters =
    filter.project !== null || filter.statuses.length > 0 || filter.types.length > 0;

  const change = useCallback(
    (edit: (next: URLSearchParams) => void) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          edit(next);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const setProject = useCallback(
    (project: JobsFilter["project"]) => {
      change((next) => {
        next.delete(PROJECT_PARAM);
        if (project !== null) {
          next.set(PROJECT_PARAM, String(project));
        }
        next.delete(PAGE_PARAM);
      });
    },
    [change],
  );

  const setStatuses = useCallback(
    (statuses: JobStatus[]) => {
      change((next) => {
        next.delete(STATUS_PARAM);
        statuses.forEach((status) => next.append(STATUS_PARAM, status));
        next.delete(PAGE_PARAM);
      });
    },
    [change],
  );

  const setTypes = useCallback(
    (types: JobType[]) => {
      change((next) => {
        next.delete(TYPE_PARAM);
        types.forEach((type) => next.append(TYPE_PARAM, type));
        next.delete(PAGE_PARAM);
      });
    },
    [change],
  );

  const setPage = useCallback(
    (newPage: number) => {
      change((next) => {
        // The first page is the default, so it has no parameter.
        if (newPage <= 1) {
          next.delete(PAGE_PARAM);
        } else {
          next.set(PAGE_PARAM, String(newPage));
        }
      });
    },
    [change],
  );

  const clear = useCallback(() => {
    change((next) => {
      next.delete(PROJECT_PARAM);
      next.delete(STATUS_PARAM);
      next.delete(TYPE_PARAM);
      next.delete(PAGE_PARAM);
    });
  }, [change]);

  return { filter, page, hasFilters, setProject, setStatuses, setTypes, setPage, clear };
}
