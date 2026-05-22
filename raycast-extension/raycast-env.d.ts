/// <reference types="@raycast/api">

/* 🚧 🚧 🚧
 * This file is auto-generated from the extension's manifest.
 * Do not modify manually. Instead, update the `package.json` file.
 * 🚧 🚧 🚧 */

/* eslint-disable @typescript-eslint/ban-types */

type ExtensionPreferences = {}

/** Preferences accessible in all the extension's commands */
declare type Preferences = ExtensionPreferences

declare namespace Preferences {
  /** Preferences accessible in the `vut-today` command */
  export type VutToday = ExtensionPreferences & {
  /** Repository Path - Path to the local vut-mcp repository. */
  "repositoryPath": string,
  /** uv Path - Full path to uv. */
  "uvPath": string,
  /** Horizon Days - Only show actions due within this many days. */
  "horizonDays": string
}
  /** Preferences accessible in the `vut-grades` command */
  export type VutGrades = ExtensionPreferences & {
  /** Repository Path - Path to the local vut-mcp repository. */
  "repositoryPath": string,
  /** uv Path - Full path to uv. */
  "uvPath": string
}
  /** Preferences accessible in the `vut-changes` command */
  export type VutChanges = ExtensionPreferences & {
  /** Repository Path - Path to the local vut-mcp repository. */
  "repositoryPath": string,
  /** uv Path - Full path to uv. */
  "uvPath": string
}
}

declare namespace Arguments {
  /** Arguments passed to the `vut-today` command */
  export type VutToday = {}
  /** Arguments passed to the `vut-grades` command */
  export type VutGrades = {}
  /** Arguments passed to the `vut-changes` command */
  export type VutChanges = {}
}

