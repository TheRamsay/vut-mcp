import { getPreferenceValues } from "@raycast/api";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export type Preferences = {
  repositoryPath: string;
  uvPath: string;
  horizonDays?: string;
};

export async function runStudisPython<T>(
  python: string,
  args: string[] = [],
): Promise<T> {
  const preferences = getPreferenceValues<Preferences>();
  const { stdout } = await execFileAsync(
    preferences.uvPath,
    ["run", "python", "-c", python, ...args],
    {
      cwd: preferences.repositoryPath,
      maxBuffer: 1024 * 1024 * 10,
    },
  );

  return JSON.parse(stdout) as T;
}
