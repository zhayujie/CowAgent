import type {IconDefinition} from '@fortawesome/fontawesome-svg-core';
import {
  faAddressBook,
  faArrowUpRightFromSquare,
  faCalendarDays,
  faImages,
  faLocationDot,
  faMobileScreen,
  faShareNodes,
} from '@fortawesome/free-solid-svg-icons';
import type {MessageKey} from '../i18n';

/**
 * How the app shows each of the kernel's phone tools, by tool name. What they do lives in
 * the handlers; which ones exist, in the kernel's PhoneTool classes.
 */
export const PHONE_TOOLS: Record<string, {icon: IconDefinition; title: MessageKey; desc: MessageKey}> = {
  phone_open: {icon: faArrowUpRightFromSquare, title: 'phone_tool_open', desc: 'phone_tool_open_desc'},
  phone_location: {icon: faLocationDot, title: 'phone_tool_location', desc: 'phone_tool_location_desc'},
  phone_calendar: {icon: faCalendarDays, title: 'phone_tool_calendar', desc: 'phone_tool_calendar_desc'},
  phone_contacts: {icon: faAddressBook, title: 'phone_tool_contacts', desc: 'phone_tool_contacts_desc'},
  phone_photos: {icon: faImages, title: 'phone_tool_photos', desc: 'phone_tool_photos_desc'},
  phone_share: {icon: faShareNodes, title: 'phone_tool_share', desc: 'phone_tool_share_desc'},
  phone_device: {icon: faMobileScreen, title: 'phone_tool_device', desc: 'phone_tool_device_desc'},
};
