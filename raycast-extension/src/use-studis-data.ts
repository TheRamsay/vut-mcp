import { Toast, showToast } from "@raycast/api";
import { useCallback, useEffect, useRef, useState } from "react";
import { runStudisPython } from "./studis";

type UseStudisDataOptions<T> = {
  python: string;
  args?: string[];
  initialData: T;
  failureTitle: string;
  transform?: (data: T) => T;
};

export function useStudisData<T>({
  python,
  args,
  initialData,
  failureTitle,
  transform,
}: UseStudisDataOptions<T>) {
  const initialDataRef = useRef(initialData);
  const [state, setState] = useState<{
    isLoading: boolean;
    data: T;
    error?: string;
  }>({ isLoading: true, data: initialData });

  const reload = useCallback(async () => {
    setState((previous) => ({
      ...previous,
      isLoading: true,
      error: undefined,
    }));

    try {
      const data = await runStudisPython<T>(python, args ?? []);
      setState({
        isLoading: false,
        data: transform ? transform(data) : data,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setState({
        isLoading: false,
        data: initialDataRef.current,
        error: message,
      });
      await showToast({
        style: Toast.Style.Failure,
        title: failureTitle,
        message,
      });
    }
  }, [args, failureTitle, python, transform]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return {
    ...state,
    reload,
  };
}
