from common.expired_dict import ExpiredDict

USER_IMAGE_CACHE = ExpiredDict(60 * 3)
