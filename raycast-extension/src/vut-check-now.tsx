import { Toast, showToast } from "@raycast/api";
import { runStudisPython } from "./studis";

type ChangeNotification = {
  id: string;
  title: string;
  body: string;
};

type ChangeNotificationResult = {
  baseline_created: boolean;
  notifications: ChangeNotification[];
  suppressed_count: number;
};

const PYTHON = String.raw`
import asyncio
import json

from vut_studis.client import StudisClient
from vut_studis.notifications import send_macos_notification

async def main():
    client = StudisClient()
    result = await client.get_change_notifications(
        mode="fast",
        force_refresh=True,
        private=False,
        mark_delivered=False,
    )
    delivered_ids = []
    for notification in result.notifications:
        send_macos_notification(notification)
        delivered_ids.append(notification.id)
    client.record_change_notifications_delivered(delivered_ids)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))

asyncio.run(main())
`;

export default async function Command() {
  try {
    const result = await runStudisPython<ChangeNotificationResult>(PYTHON);
    await showToast(toastForResult(result));
  } catch (error) {
    await showToast({
      style: Toast.Style.Failure,
      title: "Could not check VUT changes",
      message: error instanceof Error ? error.message : String(error),
    });
  }
}

function toastForResult(result: ChangeNotificationResult): Toast.Options {
  if (result.baseline_created) {
    return {
      style: Toast.Style.Success,
      title: "VUT baseline created",
      message: "Future checks will show new changes.",
    };
  }

  if (result.notifications.length === 0) {
    return {
      style: Toast.Style.Success,
      title: "No new VUT changes",
      message:
        result.suppressed_count > 0
          ? `${result.suppressed_count} already notified`
          : undefined,
    };
  }

  if (result.notifications.length === 1) {
    const notification = result.notifications[0];
    return {
      style: Toast.Style.Success,
      title: notification.title,
      message: notification.body,
    };
  }

  return {
    style: Toast.Style.Success,
    title: `${result.notifications.length} new VUT changes`,
    message: result.notifications[0].title,
  };
}
