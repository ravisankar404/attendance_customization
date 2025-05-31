from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

# Hardcode version to avoid import issues during installation
__version__ = "0.0.1"

setup(
    name="attendance_customization",
    version=__version__,
    description="Custom fields and logic for Attendance tracking",
    author="Your Name",
    author_email="your-email@example.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)