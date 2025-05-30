from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

from attendance_customization import __version__ as version

setup(
    name="attendance_customization",
    version=version,
    description="Custom fields and logic for Attendance tracking",
    author="Your Name",
    author_email="your-email@example.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)


