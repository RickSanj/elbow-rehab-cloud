from pydantic import BaseModel

class SignupSchema(BaseModel):
    email: str
    password: str

    class Config:
        schema_extra = {
            "example": {
                "email": "example@gmail.com",
                "password": "examplepassword123",
            }
        }

class LoginSchema(BaseModel):
    email: str
    password: str

    class Config:
        schema_extra = {
            "example": {
                "email": "example@gmail.com",
                "password": "examplepassword123",
            }
        }

class SignupResponse(BaseModel):
    message: str
    doctor_id: str
    warning: str | None = None
