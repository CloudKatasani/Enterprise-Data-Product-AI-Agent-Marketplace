/**
 * HTTP status codes.
 *
 * The only file in `portal/` outside `styles/` allowed to carry bare numeric
 * literals (see scripts/lint/no_magic_numbers.py), for the same reason as
 * services/common/http_status.py: a status code is not a threshold, and
 * confining them to one module keeps them from reading like one.
 */
export const OK = 200;
export const NO_CONTENT = 204;
export const BAD_REQUEST = 400;
export const UNAUTHORIZED = 401;
export const FORBIDDEN = 403;
export const NOT_FOUND = 404;
export const UNPROCESSABLE_ENTITY = 422;
export const FAILED_DEPENDENCY = 424;
export const TOO_MANY_REQUESTS = 429;
export const INTERNAL_SERVER_ERROR = 500;
export const SERVICE_UNAVAILABLE = 503;
